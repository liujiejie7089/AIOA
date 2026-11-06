package cn.aios.resource.connector.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.resource.connector.entity.ConnectorConnection;
import cn.aios.resource.connector.entity.ConnectorDef;
import cn.aios.resource.connector.mapper.ConnectorConnectionMapper;
import cn.aios.resource.connector.support.QqMailProbe;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 连接状态机里「成功路径必须把历史错误清掉」（A4）。
 *
 * <p><b>缺陷</b>：{@code connectWithCredential} 的成功分支原先调 {@code updateById(c)}，
 * 而 {@code setLastError(null)} / {@code setDisconnectedAt(null)} 在 MyBatis-Plus 的
 * NOT_NULL 字段策略下**不进 UPDATE 语句**。于是重连成功后，库里仍挂着上一次的错误文案
 * 与断开时间 —— 面板上出现「状态=已连接，却写着『授权码错误』、断开于昨天」的自相矛盾。
 * {@code disconnect()} 早就换成了显式 set 的写法，连接这条一直漏着（{@code verify()} 同样）。</p>
 *
 * <p><b>判据</b>：成功路径不允许出现 {@code updateById}；必须是一条显式 set 的
 * UPDATE，且 SET 子句里点名 {@code last_error} / {@code disconnected_at}（值为 NULL）。</p>
 */
class ConnectorConnectionServiceTest {

    private ConnectorConnectionMapper mapper;
    private QqMailProbe probe;
    private ConnectorConnectionService service;

    /**
     * {@code LambdaUpdateWrapper#getSqlSet()} 要把 lambda 还原成列名，必须有 TableInfo 缓存；
     * 纯单测没有 Spring/MyBatis 启动过程，得手动初始化一次。
     */
    @BeforeAll
    static void initTableInfo() {
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""), ConnectorConnection.class);
    }

    @BeforeEach
    void setUp() {
        mapper = mock(ConnectorConnectionMapper.class);
        ConnectorCatalogService catalog = mock(ConnectorCatalogService.class);
        SecretCodec codec = mock(SecretCodec.class);
        probe = mock(QqMailProbe.class);

        ConnectorDef def = new ConnectorDef();
        def.setCode("qq_mail");
        def.setAuthMode(ConnectorDef.AUTH_MODE_CREDENTIAL);
        when(catalog.requireDef("qq_mail")).thenReturn(def);
        when(codec.encrypt(anyString())).thenReturn("ENC");

        service = new ConnectorConnectionService(mapper, catalog, codec, probe);
    }

    private static AuthUser user() {
        return AuthUser.of(1L, 7L, "test", "测试账号", List.of());
    }

    private static ConnectorConnection existing() {
        ConnectorConnection c = new ConnectorConnection();
        c.setId(42L);
        c.setTenantId(1L);
        c.setUserId(7L);
        c.setConnectorCode("qq_mail");
        c.setStatus(ConnectorConnection.STATUS_UNVERIFIED);
        c.setLastError("授权码错误");
        c.setDisconnectedAt(java.time.LocalDateTime.now().minusDays(1));
        return c;
    }

    @SuppressWarnings("unchecked")
    private LambdaUpdateWrapper<ConnectorConnection> captureUpdate() {
        ArgumentCaptor<Wrapper<ConnectorConnection>> cap = ArgumentCaptor.forClass(Wrapper.class);
        verify(mapper).update(isNull(), cap.capture());
        return (LambdaUpdateWrapper<ConnectorConnection>) cap.getValue();
    }

    @Test
    @DisplayName("重连成功：显式 SET last_error / disconnected_at，不再用 updateById")
    void reconnectClearsStaleErrorAndDisconnectTime() {
        when(mapper.selectOne(any())).thenReturn(existing());
        when(probe.verify("a@qq.com", "authcode")).thenReturn(null);

        service.connectWithCredential(user(), "qq_mail",
                Map.of("email", "a@qq.com", "authCode", "authcode"));

        verify(mapper, never()).updateById(any(ConnectorConnection.class));
        String set = captureUpdate().getSqlSet();
        assertNotNull(set);
        assertTrue(set.contains("last_error"), "SET 必须点名 last_error（否则旧错误清不掉）：" + set);
        assertTrue(set.contains("disconnected_at"), "SET 必须点名 disconnected_at：" + set);
        assertTrue(set.contains("status"), "状态同样要显式写：" + set);
    }

    @Test
    @DisplayName("首次连接（无既有行）走 insert，不带 lastError / disconnectedAt")
    void firstConnectInsertsCleanRow() {
        when(mapper.selectOne(any())).thenReturn(null);
        when(probe.verify("a@qq.com", "authcode")).thenReturn(null);

        service.connectWithCredential(user(), "qq_mail",
                Map.of("email", "a@qq.com", "authCode", "authcode"));

        ArgumentCaptor<ConnectorConnection> cap = ArgumentCaptor.forClass(ConnectorConnection.class);
        verify(mapper).insert(cap.capture());
        ConnectorConnection row = cap.getValue();
        assertFalse(row.getStatus() == null, "新行必须有状态");
        assertTrue(ConnectorConnection.STATUS_CONNECTED.equals(row.getStatus()));
        assertTrue(row.getLastError() == null, "新行不该带错误文案");
        assertTrue(row.getDisconnectedAt() == null, "新行不该带断开时间");
        verify(mapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("校验失败不写库（仍然只报错）")
    void failedProbeWritesNothing() {
        when(probe.verify("a@qq.com", "bad")).thenReturn("认证失败");

        try {
            service.connectWithCredential(user(), "qq_mail",
                    Map.of("email", "a@qq.com", "authCode", "bad"));
        } catch (RuntimeException expected) {
            // 预期：BizException(400)
        }
        verify(mapper, never()).update(any(), any());
        verify(mapper, never()).updateById(any(ConnectorConnection.class));
        verify(mapper, never()).insert(any(ConnectorConnection.class));
    }
}

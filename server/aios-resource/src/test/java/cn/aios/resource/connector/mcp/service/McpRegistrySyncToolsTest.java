package cn.aios.resource.connector.mcp.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.resource.connector.mcp.config.McpProperties;
import cn.aios.resource.connector.mcp.entity.McpServer;
import cn.aios.resource.connector.mcp.entity.McpServerTool;
import cn.aios.resource.connector.mcp.mapper.McpServerMapper;
import cn.aios.resource.connector.mcp.mapper.McpServerToolMapper;
import cn.aios.resource.connector.service.ConnectorCatalogService;
import cn.aios.resource.connector.service.ConnectorConnectionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工具目录同步时的「软删复活」（A2）。
 *
 * <p><b>缺陷</b>：{@code syncTools} 原先是 {@code row.setDeletedAt(null)} + {@code updateById}。
 * 两处都不成立 —— 对新对象（id=null）它走 insert，压根不看该字段；对已存在行，
 * MyBatis-Plus 的 NOT_NULL 策略会静默跳过 null 字段。何况唯一键
 * {@code uk_mcp_tool(server_id, name)} 不区分删除态、{@code @TableLogic} 又让
 * select/update 都够不到软删行 ⇒ 结果是「恢复不了，而且下次 sync 会 insert 撞唯一键」。</p>
 *
 * <p><b>判据</b>（本测试钉的就是这两条）：</p>
 * <ol>
 *   <li>写目录前必须对每个 incoming 工具调一次裸 SQL {@code restoreDeleted}，且**在** selectList 之前
 *       （顺序错了等于没复活：查不到就还是会走 insert）；</li>
 *   <li>不再出现「靠 setDeletedAt(null) 恢复」的路径 —— 新增行 insert 时不该带 deletedAt。</li>
 * </ol>
 */
class McpRegistrySyncToolsTest {

    private McpServerToolMapper toolMapper;
    private McpRegistryService service;

    @BeforeEach
    void setUp() {
        McpServerMapper serverMapper = mock(McpServerMapper.class);
        toolMapper = mock(McpServerToolMapper.class);
        service = new McpRegistryService(serverMapper, toolMapper,
                mock(ConnectorConnectionService.class), mock(ConnectorCatalogService.class),
                mock(McpProbeClient.class), mock(McpProperties.class), mock(SecretCodec.class));
    }

    private static McpProbeClient.Tool tool(String name, boolean readOnly) {
        McpProbeClient.Tool t = new McpProbeClient.Tool();
        t.setName(name);
        t.setDescription(name + " 的描述");
        t.setReadOnly(readOnly);
        return t;
    }

    private static McpServer server() {
        McpServer s = new McpServer();
        s.setId(11L);
        s.setTenantId(0L);
        s.setCode("qq_mail");
        return s;
    }

    /** syncTools 是私有方法：这条链路要真库才走得到，单测直接打靶那段逻辑。 */
    private int sync(McpServer s, List<McpProbeClient.Tool> tools) throws Exception {
        Method m = McpRegistryService.class.getDeclaredMethod("syncTools", McpServer.class, List.class);
        m.setAccessible(true);
        return (int) m.invoke(service, s, tools);
    }

    @Test
    @DisplayName("复活裸 SQL 必须在 selectList 之前，且每个工具各一次")
    void restoreDeletedRunsBeforeSelect() throws Exception {
        when(toolMapper.selectList(any())).thenReturn(List.of());

        sync(server(), List.of(tool("send_mail", false), tool("read_message", true)));

        InOrder order = inOrder(toolMapper);
        order.verify(toolMapper).restoreDeleted(11L, "send_mail");
        order.verify(toolMapper).restoreDeleted(11L, "read_message");
        order.verify(toolMapper).selectList(any());
    }

    @Test
    @DisplayName("软删行复活后查得到 ⇒ 走 update 而不是 insert（不再撞 uk_mcp_tool）")
    void revivedRowIsUpdatedNotInserted() throws Exception {
        // 模拟「restoreDeleted 之后 selectList 就能看见那行」——真实库里正是这个因果关系
        McpServerTool existing = new McpServerTool();
        existing.setId(77L);
        existing.setServerId(11L);
        existing.setName("send_mail");
        when(toolMapper.selectList(any())).thenReturn(List.of(existing));

        sync(server(), List.of(tool("send_mail", false)));

        verify(toolMapper).updateById(any(McpServerTool.class));
        verify(toolMapper, never()).insert(any(McpServerTool.class));
    }

    @Test
    @DisplayName("全新工具仍然 insert，且不带 deletedAt（不再靠 setDeletedAt(null) 兜）")
    void brandNewToolIsInsertedWithoutDeletedAt() throws Exception {
        when(toolMapper.selectList(any())).thenReturn(List.of());
        List<McpServerTool> inserted = new ArrayList<>();
        when(toolMapper.insert(any(McpServerTool.class))).thenAnswer(inv -> {
            inserted.add(inv.getArgument(0));
            return 1;
        });

        int n = sync(server(), List.of(tool("new_tool", false)));

        assertEquals(1, n);
        assertEquals(1, inserted.size());
        McpServerTool row = inserted.get(0);
        assertNotNull(row.getServerId());
        assertEquals("new_tool", row.getName());
        assertNull(row.getDeletedAt(), "新增行不能带 deletedAt");
    }

    @Test
    @DisplayName("工具从目录里消失 ⇒ 逻辑删除（这条行为不能被复活动作带坏）")
    void disappearedToolIsSoftDeleted() throws Exception {
        McpServerTool gone = new McpServerTool();
        gone.setId(88L);
        gone.setServerId(11L);
        gone.setName("old_tool");
        when(toolMapper.selectList(any())).thenReturn(List.of(gone));

        sync(server(), List.of(tool("send_mail", false)));

        verify(toolMapper).updateById(any(McpServerTool.class));
        assertNotNull(gone.getDeletedAt(), "消失的工具必须被软删");
        // 同时也复活了 incoming 的那个（两个 restore 各一次，互不干扰）
        verify(toolMapper, times(1)).restoreDeleted(11L, "send_mail");
        verify(toolMapper, never()).restoreDeleted(anyLong(), eq("old_tool"));
    }
}

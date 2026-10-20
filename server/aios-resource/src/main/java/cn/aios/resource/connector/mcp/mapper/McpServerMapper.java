package cn.aios.resource.connector.mcp.mapper;

import cn.aios.resource.connector.mcp.entity.McpServer;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface McpServerMapper extends BaseMapper<McpServer> {

    /**
     * 按 {@code (tenant_id, code)} 取一行，<b>包含已逻辑删除的行</b>。
     *
     * <p><b>为什么要这个「不守规矩」的查询</b>：实体上的 {@code @TableLogic} 会让所有
     * MP 生成的 SQL 自动追加 {@code deleted_at IS NULL}，而唯一键
     * {@code uk_mcp_server(tenant_id, code)} <b>不含</b> {@code deleted_at} ⇒ 被软删的行会永久占住
     * 这个 code。此时「先查重、再 insert」的做法必然漏判（查重看不见死行），insert 直接撞
     * DuplicateKey（实测：E2E 第二次跑、注册同一个 code，接口 500）。@Select 手写 SQL
     * 不受 {@code @TableLogic} 影响，正好用来看见死行。</p>
     */
    @Select("SELECT * FROM mcp_server WHERE tenant_id = #{tenantId} AND code = #{code} LIMIT 1")
    McpServer selectIncludingDeleted(@Param("tenantId") Long tenantId, @Param("code") String code);

    /**
     * 物理删除一行（含软删行），用于「复活同一个 code」前清场。
     *
     * <p>不能复用 {@code deleteById}：那是逻辑删除，行还在、唯一键仍被占。审计表
     * {@code mcp_tool_audit} 只存 {@code server_code} 字符串、无外键，所以物理删除不破坏审计。</p>
     */
    @Delete("DELETE FROM mcp_server WHERE id = #{id}")
    int purgeById(@Param("id") Long id);
}

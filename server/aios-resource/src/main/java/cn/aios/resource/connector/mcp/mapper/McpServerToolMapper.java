package cn.aios.resource.connector.mcp.mapper;

import cn.aios.resource.connector.mcp.entity.McpServerTool;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface McpServerToolMapper extends BaseMapper<McpServerTool> {

    /** 物理清掉某服务器的全部工具目录行（含软删行），与 {@link McpServerMapper#purgeById} 配套。 */
    @Delete("DELETE FROM mcp_server_tool WHERE server_id = #{serverId}")
    int purgeByServerId(@Param("serverId") Long serverId);

    /**
     * 把「曾被逻辑删除」的同名工具行原地恢复（{@code deleted_at} → NULL）。
     *
     * <p><b>为什么必须是裸 SQL</b>：{@code uk_mcp_tool(server_id, name)} 是**唯一键**，
     * 它不区分删除态 —— 软删行仍然占着那个键。而 MyBatis-Plus 的 {@code @TableLogic}
     * 会给 select / update 自动追加 {@code deleted_at IS NULL}，于是两条常规路都堵死：</p>
     * <ol>
     *   <li>{@code selectList} 看不到软删行 ⇒ {@code syncTools} 以为这是「新工具」⇒ 走 insert
     *       ⇒ 撞唯一键 {@code DuplicateKeyException}（信任/刷新整条链路直接 500）；</li>
     *   <li>{@code LambdaUpdateWrapper.set(deletedAt, null)} 也匹配不到软删行 ⇒ 恢复变空操作。</li>
     * </ol>
     * <p>所以只能绕开逻辑删除拦截，用裸 SQL 显式置 NULL。场景很常见：某 server 某次探活
     * 少了一个工具（被软删），下次探活它又回来了 —— 不恢复就必然撞键。</p>
     */
    @Update("UPDATE mcp_server_tool SET deleted_at = NULL, updated_at = NOW(6) "
            + "WHERE server_id = #{serverId} AND name = #{name} AND deleted_at IS NOT NULL")
    int restoreDeleted(@Param("serverId") Long serverId, @Param("name") String name);
}

package cn.aios.resource.connector.mcp.mapper;

import cn.aios.resource.connector.mcp.entity.McpServerTool;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface McpServerToolMapper extends BaseMapper<McpServerTool> {

    /** 物理清掉某服务器的全部工具目录行（含软删行），与 {@link McpServerMapper#purgeById} 配套。 */
    @Delete("DELETE FROM mcp_server_tool WHERE server_id = #{serverId}")
    int purgeByServerId(@Param("serverId") Long serverId);
}

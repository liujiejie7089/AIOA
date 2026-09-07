package cn.aioa.common.mybatis;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;

import java.io.IOException;
import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;

/**
 * jsonb 列通用 TypeHandler：以 Types.OTHER 写入，避免 pgjdbc 把 JSON 文本当 varchar 导致类型不匹配。
 */
public abstract class AbstractJsonbTypeHandler<T> extends BaseTypeHandler<T> {

    protected static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    protected abstract T fromJson(String json) throws IOException;

    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, T parameter, JdbcType jdbcType) throws SQLException {
        try {
            ps.setObject(i, OBJECT_MAPPER.writeValueAsString(parameter), Types.OTHER);
        } catch (IOException e) {
            throw new SQLException("Failed to serialize jsonb parameter: " + e.getMessage(), e);
        }
    }

    @Override
    public T getNullableResult(ResultSet rs, String columnName) throws SQLException {
        return read(rs.getString(columnName));
    }

    @Override
    public T getNullableResult(ResultSet rs, int columnIndex) throws SQLException {
        return read(rs.getString(columnIndex));
    }

    @Override
    public T getNullableResult(CallableStatement cs, int columnIndex) throws SQLException {
        return read(cs.getString(columnIndex));
    }

    private T read(String json) throws SQLException {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return fromJson(json);
        } catch (IOException e) {
            throw new SQLException("Failed to deserialize jsonb column: " + e.getMessage(), e);
        }
    }
}

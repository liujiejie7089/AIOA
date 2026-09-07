package cn.aioa.common.mybatis;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;

import java.io.IOException;
import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

/**
 * JSON 列通用 TypeHandler（兼容 MySQL 8 JSON 类型）。
 * MySQL Connector/J 接收 String 形式的 JSON 文本写入 JSON 列，读取时也以 String 取回，
 * 故统一用 setString / getString 处理，避免 pgjdbc 的 Types.OTHER 语义。
 */
public abstract class AbstractJsonTypeHandler<T> extends BaseTypeHandler<T> {

    protected static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    protected abstract T fromJson(String json) throws IOException;

    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, T parameter, JdbcType jdbcType) throws SQLException {
        try {
            ps.setString(i, OBJECT_MAPPER.writeValueAsString(parameter));
        } catch (IOException e) {
            throw new SQLException("Failed to serialize json parameter: " + e.getMessage(), e);
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
            throw new SQLException("Failed to deserialize json column: " + e.getMessage(), e);
        }
    }
}

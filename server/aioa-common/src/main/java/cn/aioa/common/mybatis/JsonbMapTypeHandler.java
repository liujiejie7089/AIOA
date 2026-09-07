package cn.aioa.common.mybatis;

import com.fasterxml.jackson.core.type.TypeReference;

import java.io.IOException;
import java.util.Map;

/**
 * jsonb 对象列（Map）TypeHandler。
 */
public class JsonbMapTypeHandler extends AbstractJsonbTypeHandler<Map<String, Object>> {

    private static final TypeReference<Map<String, Object>> TYPE = new TypeReference<>() {
    };

    @Override
    protected Map<String, Object> fromJson(String json) throws IOException {
        return OBJECT_MAPPER.readValue(json, TYPE);
    }
}

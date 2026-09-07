package cn.aioa.common.mybatis;

import com.fasterxml.jackson.core.type.TypeReference;

import java.io.IOException;
import java.util.Map;

/**
 * JSON 对象列（Map）TypeHandler（兼容 MySQL 8 JSON 类型）。
 */
public class JsonMapTypeHandler extends AbstractJsonTypeHandler<Map<String, Object>> {

    private static final TypeReference<Map<String, Object>> TYPE = new TypeReference<>() {
    };

    @Override
    protected Map<String, Object> fromJson(String json) throws IOException {
        return OBJECT_MAPPER.readValue(json, TYPE);
    }
}

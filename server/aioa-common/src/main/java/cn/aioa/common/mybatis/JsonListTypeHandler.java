package cn.aioa.common.mybatis;

import com.fasterxml.jackson.core.type.TypeReference;

import java.io.IOException;
import java.util.List;

/**
 * JSON 数组列（List）TypeHandler（兼容 MySQL 8 JSON 类型）。
 */
public class JsonListTypeHandler extends AbstractJsonTypeHandler<List<Object>> {

    private static final TypeReference<List<Object>> TYPE = new TypeReference<>() {
    };

    @Override
    protected List<Object> fromJson(String json) throws IOException {
        return OBJECT_MAPPER.readValue(json, TYPE);
    }
}

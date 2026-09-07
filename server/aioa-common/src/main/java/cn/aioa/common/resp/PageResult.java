package cn.aioa.common.resp;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * 简单分页结果。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class PageResult<T> {

    private List<T> list = new ArrayList<>();
    private long total = 0L;
    private long page = 1L;
    private long size = 20L;

    public static <T> PageResult<T> of(List<T> list, long total, long page, long size) {
        return new PageResult<>(list == null ? new ArrayList<>() : list, total, page, size);
    }
}

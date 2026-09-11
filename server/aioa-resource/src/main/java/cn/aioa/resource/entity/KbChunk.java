package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 知识库切片：文档入库后按段落切分的最小单元，是检索命中与引用溯源（FR-D5）的数据源。
 */
@Data
@TableName("kb_chunk")
public class KbChunk {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long docId;

    private Long userId;

    private Integer chunkIndex;

    private String content;

    /** 向量（float32 序列，小端）；未向量化为 null。 */
    private byte[] embedding;

    /** 向量化 provider：local / bge-small-zh。 */
    private String embeddingProvider;

    /** 向量维度，与 provider 绑定（local=256，bge-small-zh=512）。 */
    private Integer embeddingDims;

    private LocalDateTime embeddingAt;

    private LocalDateTime createdAt;

    @TableLogic
    private LocalDateTime deletedAt;
}

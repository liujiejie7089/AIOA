package cn.aioa.chat.service;

import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 内容合规护栏（FR-H3 内容合规双审 + FR-D6 审批卡点演示）：
 *   · 输入审核：发起会话前检查用户输入，命中即拒绝（400 + 合规提示）
 *   · 输出审核：回答完成落库前检查生成内容，命中即中止应答、落合规提示、置 FAILED
 *   · 场景识别：输出涉及"对外发布/发文"场景时，注入 approval.required 卡片事件
 * 一期使用内置演示词表（内容安全门禁架构占位：正式版可接审核模型 + 租户自定义词库）。
 */
@Service
public class ContentGuardService {

    /** 违规词表（演示级，涵盖主要违规类目；命中即中止）。 */
    private static final List<String> BLOCK_WORDS = List.of(
            "分裂国家", "颠覆国家政权", "恐怖袭击", "爆炸物制作", "枪支买卖",
            "制毒方法", "冰毒配方", "海洛因", "淫秽色情内容", "传播淫秽",
            "赌博网站", "网络博彩", "洗钱通道", "电信诈骗教程", "诈骗话术库");

    /** 对外发布场景词（FR-D6：涉及则出现"提交审批"卡片，进入演示审批链路）。 */
    private static final List<String> PUBLISH_WORDS = List.of(
            "对外发布", "对外发文", "发文申请", "正式发文", "公开发布", "对外公告", "官方声明");

    /** 输入命中提示。 */
    public String inputBlockMessage(String hit) {
        return "您的内容包含违规敏感词（" + hit + "），已被内容安全策略拦截，请调整后重试。";
    }

    /** 输出命中提示（作为 assistant 消息落库，用户端可见）。 */
    public String outputBlockMessage(String hit) {
        return "本次回答内容命中内容安全策略（敏感词：" + hit + "），应答已中止。"
                + "如属正常业务需要，请联系管理员调整审核配置。";
    }

    /**
     * 查找文本命中的违规词；未命中返回 null。
     * 大小写不敏感、去空白后匹配，容忍用户以空格/标点拆词绕过的简单尝试。
     */
    public String findHit(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        String normalized = normalize(text);
        for (String word : BLOCK_WORDS) {
            if (normalized.contains(normalize(word))) {
                return word;
            }
        }
        return null;
    }

    /** 输出是否涉及对外发布场景（FR-D6 审批卡点）。 */
    public String findPublishScenario(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        String normalized = normalize(text);
        for (String word : PUBLISH_WORDS) {
            if (normalized.contains(normalize(word))) {
                return word;
            }
        }
        return null;
    }

    private static String normalize(String text) {
        return text == null ? "" : text.replaceAll("\\s+", "").toLowerCase();
    }
}

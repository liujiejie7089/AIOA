package cn.aioa.gitee.client;

import java.util.List;
import java.util.Map;

/**
 * 代码托管方客户端契约（Gitee / Gitea / …）。
 *
 * <p><b>为什么抽这一层</b>：本平台对「仓库托管」的需求是稳定的（建仓、配 Webhook、
 * 网页提交、同步成员、读提交）；而承载它的服务商是<b>可替换的</b>。此前
 * {@code GiteeClient} 是唯一实现且被 8 个服务<b>直接按具体类注入</b>，于是
 * 「换一家托管方」等于逐个改这 8 处 —— 替换成本与耦合度成正比。抽出本接口后，
 * 上层只依赖契约，切换实现只动装配。</p>
 *
 * <p><b>调用方须知（重要）</b>：接口里的方法<b>不是</b>「某家 API 的直译」，
 * 而是<b>平台语义</b>。各实现负责把平台语义映射到自家线格式。以下是已知的
 * <b>硬分歧点</b>，实现方必须逐条处理，否则会出现「建仓成功但 Webhook 静默失败」
 * 这类最难查的半成品状态：</p>
 *
 * <ol>
 *   <li><b>仓库名（{@link #createOrgRepo}）</b>：Gitee 的 {@code name}（展示名，可含中文）
 *       与 {@code path}（URL 片段）是<b>两个字段</b>；Gitea 只有一个 {@code name}
 *       同时充当 URL 片段。<b>不支持双字段的实现必须显式决定</b>用哪个 —— 用 {@code path}
 *       则丢失中文展示名；用 {@code name} 则中文进 URL。禁止静默忽略其中一个。</li>
 *   <li><b>Webhook 校验（{@link #createHook}）</b>：Gitee 是<b>共享密钥明文比对</b>
 *       （回调头 {@code X-Gitee-Token} 等于此处 secret）；Gitea 是
 *       <b>HMAC-SHA256 签名</b>（回调头 {@code X-Gitea-Signature} = 原始报文体的
 *       HMAC-SHA256 十六进制，<b>无前缀</b>；兼容 {@code X-Hub-Signature-256}，
 *       带 {@code sha256=} 前缀）。把这两者搞混的后果是「配置成功、回调全被拒」。</li>
 *   <li><b>事件头与事件名（{@link #createHook} 触发的事件）</b>：Gitee 用
 *       {@code X-Gitee-Event}（如 {@code Merge Request Hook}）；Gitea 用
 *       {@code X-Gitea-Event}（如 {@code pull_request} / {@code issues} /
 *       {@code issue_comment}）。<b>事件名是下划线风格且存在子串包含关系</b>
 *       （{@code issue_comment} 含 {@code issue}），按子串匹配会误分类 —— 必须精确匹配。</li>
 *   <li><b>OAuth2（{@link #authorizeUrl} / {@link #exchangeCode} / {@link #refreshToken}）</b>：
 *       授权端点 Gitee 为 {@code /oauth/authorize}、Gitea 为 {@code /login/oauth/authorize}；
 *       换令牌端点 Gitee 为 {@code /oauth/token}、Gitea 为 {@code /login/oauth/access_token}；
 *       且 <b>scope 词表完全不同</b>（Gitee: {@code projects}/{@code hook}；
 *       Gitea: {@code repo}/{@code read:repository}/…），<b>没有交集</b>。</li>
 *   <li><b>分页（{@link #listHooks} / {@link #listCollaborators} / {@link #listBranches}）</b>：
 *       Gitee 用 {@code per_page}（上限 100）；Gitea 用 {@code limit}，
 *       且服务端有<b>硬上限</b>（实测 {@code max_response_items=50}，
 *       即便传 {@code limit=100} 也只回 50）。因此「一次拉全量」在 Gitea 上不成立，
 *       凡是可能超 50 条的列表<b>必须翻页</b>，否则静默截断。</li>
 * </ol>
 *
 * <p><b>错误约定</b>：所有实现失败时抛 {@link RepoProviderException}（或其子类，
 * 如 {@link GiteeApiException}），由 {@code GiteeExceptionAdvice} 统一翻译成
 * 「HTTP 200 + 业务错误码」，<b>不得</b>让异常裸奔到全局兜底（那会变成无信息量的 500）。</p>
 */
public interface RepoProviderClient {

    // ======================================================================
    // OAuth2
    // ======================================================================

    /**
     * 拼**授权页**地址（由用户浏览器跳转，非服务端调用）。
     *
     * <p>实现必须使用「授权页基址」而非「服务端 API 基址」：曾复用同一个配置键，
     * 导致把服务端指向本地桩的部署顺手把用户也送进桩，用户看到假授权页、
     * 被签发假身份后显示「绑定成功」—— 看似成功，实则从未经过真实授权。</p>
     */
    String authorizeUrl(String state);

    /** 授权跳转落地的域名（用于界面提示与排障）。 */
    String authorizeHost();

    /**
     * 授权跳转是否指向**非生产**域（本地桩 / 自建代理）。
     *
     * <p>返回 true 时，调用方<b>必须显式暴露</b>给用户/运维，而不是让它表现成一次
     * 正常的授权成功 —— 「假成功」比报错更难发现。</p>
     */
    boolean authorizeHostIsSandbox();

    /**
     * 授权码换令牌。
     *
     * @return 归一化视图：{@code access_token} / {@code refresh_token} /
     *         {@code expires_in} / {@code scope}
     */
    Map<String, Object> exchangeCode(String code);

    /** 用 refresh_token 换新令牌（同上返回结构）。 */
    Map<String, Object> refreshToken(String refreshToken);

    // ======================================================================
    // 用户与组织
    // ======================================================================

    /** 当前令牌对应的托管方用户（用于回填 uid / login 做身份映射）。 */
    Map<String, Object> getUser(String token);

    /**
     * 组织信息（带令牌），用于校验当前账号对该组织的可见性。
     *
     * <p>注意：成员未必能看到组织，故这是 best-effort 探测，调用方须容忍失败。</p>
     */
    Map<String, Object> getOrg(String token, String org);

    // ======================================================================
    // 仓库
    // ======================================================================

    /**
     * 该平台新建仓库的**默认分支名**。
     *
     * <p><b>为什么必须在契约里显式声明</b>：Gitee 是 {@code master}，Gitea 1.26 实例实测是
     * {@code main}（取决于服务端 {@code DEFAULT_BRANCH} 配置）。分支名写错不会报「配置错」，
     * 只会让**读写文件、文件链接、目录浏览**全部 404 —— 症状是「新项目一打开就没内容」。</p>
     *
     * <p><b>这只是兜底值</b>：权威来源永远是建仓/查询接口返回的 {@code default_branch}
     * （实例可自行改这个设置），所以调用方应优先取接口值，仅在接口没给时回落到这里。</p>
     */
    String defaultBranch();

    /**
     * 在**组织**命名空间下建仓。
     *
     * @param name        展示名（Gitee 可含中文）
     * @param path        URL 片段（Gitee 专用；Gitea 无此概念，见类注释分歧点 1）
     * @param description 描述
     * @param isPrivate   是否私有
     * @param autoInit    是否自动初始化（带 README），避免空仓库首次 push 无处可依
     */
    Map<String, Object> createOrgRepo(String token, String org, String name, String path,
                                      String description, boolean isPrivate, boolean autoInit);

    /** 在**用户**命名空间下建仓（未配置组织时的降级路径）。 */
    Map<String, Object> createUserRepo(String token, String name, String description,
                                       boolean isPrivate, boolean autoInit);

    /** 仓库详情。 */
    Map<String, Object> getRepo(String token, String owner, String repo);

    /** 删除仓库（不可逆，调用方须显式确认）。 */
    void deleteRepo(String token, String owner, String repo);

    // ======================================================================
    // Webhook
    // ======================================================================

    /**
     * 创建 Webhook。
     *
     * <p><b>本方法的最大陷阱</b>：{@code secret} 的<b>用途在两家完全不同</b> ——
     * Gitee 作为明文共享密钥（回调头 {@code X-Gitee-Token} 与之比对）；
     * Gitea 作为 HMAC-SHA256 的密钥（回调头 {@code X-Gitea-Signature}）。
     * 两者都叫「secret」，但校验算法不通用。详见类注释分歧点 2。</p>
     *
     * @param push / pr / issue / note 分别开关对应事件的订阅
     */
    Map<String, Object> createHook(String token, String owner, String repo,
                                   String url, String secret, boolean push, boolean pr,
                                   boolean issue, boolean note);

    /**
     * Webhook 事件名列表（**展示用**，与 {@link #createHook} 收到同一组开关）。
     *
     * <p><b>为什么要单独一个方法</b>：两家的开关是同一套（push/pr/issue/note），但
     * <b>事件名完全不同</b> —— Gitee 落 {@code merge_requests} / {@code notes}，
     * Gitea 落 {@code pull_request} / {@code issue_comment}。项目详情页会把这张列表
     * 逐个渲染成标签，落库时写死任一家的词表，切到另一家就会<b>明确地说错自己订了什么</b>。
     * 真机实测（2026-09-18）：Gitea 项目详情页显示 {@code push,merge_requests,issues,notes}，
     * 而仓库上真实订阅的是 {@code push,pull_request,issues,issue_comment,…}。</p>
     *
     * <p>必须与 {@link #createHook} 用<b>同一组入参</b>调用，否则展示与事实再次分叉。</p>
     */
    List<String> hookEventNames(boolean push, boolean pr, boolean issue, boolean note);

    /**
     * Webhook 列表。
     *
     * <p>调用方若用于「判重/清理」，必须考虑分页截断（见类注释分歧点 5）。</p>
     */
    List<Map<String, Object>> listHooks(String token, String owner, String repo);

    /** 删除 Webhook。 */
    void deleteHook(String token, String owner, String repo, Long hookId);

    // ======================================================================
    // 内容（网页提交走这里）
    // ======================================================================

    /**
     * 读取文件或目录。
     *
     * <p><b>返回类型必须在实现里归一化</b>：同一个端点按 path 指向返回<b>两种形状</b>
     * —— 目录是数组、文件是对象。若直接透传原始 JSON 节点，调用方的
     * {@code instanceof List} 永远为 false，会把目录误判成文件并拿到一片 null 字段。</p>
     *
     * @return 目录 → {@code List<Map<String,Object>>}；文件 → {@code Map<String,Object>}
     */
    Object getContents(String token, String owner, String repo, String path, String ref);

    /**
     * 新建文件。
     *
     * <p>只用于<b>新建</b>；对已存在的文件必须走 {@link #updateFile}（带旧 sha），
     * 否则服务端返回 422（无法判断是覆盖还是冲突）。</p>
     *
     * @param contentBase64 文件内容 Base64（Gitee 要求，不接受明文）
     */
    Map<String, Object> putFile(String token, String owner, String repo, String path,
                                String contentBase64, String message, String branch);

    /**
     * 更新已有文件。
     *
     * @param sha 该文件**当前**的 blob sha（服务端据此做并发冲突检测）
     */
    Map<String, Object> updateFile(String token, String owner, String repo, String path,
                                   String contentBase64, String message, String branch, String sha);

    /** 分支列表（默认分支判定用；同样受分页上限影响）。 */
    List<Map<String, Object>> listBranches(String token, String owner, String repo);

    // ======================================================================
    // 成员权限（协作者）
    // ======================================================================

    /** 协作者列表（多为公开可读）。 */
    List<Map<String, Object>> listCollaborators(String token, String owner, String repo);

    /**
     * 添加/更新协作者。
     *
     * @param permission read / write / admin（各家大小写敏感度不同，实现须归一化）
     */
    void addCollaborator(String token, String owner, String repo, String username, String permission);

    /** 移除协作者。 */
    void removeCollaborator(String token, String owner, String repo, String username);

    // ======================================================================
    // Webhook 回调的接收侧契约
    //
    // 校验方式**不是可选项**：这是平台上唯一不需要登录态就能写数据的入口。
    // 两家的机制完全不同（明文共享密钥 vs HMAC 签名），因此必须由实现自己承担，
    // 而不是在上层按类名分支 —— 那样新增一家就会漏掉一处，而漏掉的后果是
    // 「任何人都能伪造提交记录」。
    // ======================================================================

    /** 事件头名（Gitee：{@code X-Gitee-Event}；Gitea：{@code X-Gitea-Event}）。 */
    String webhookEventHeader();

    /**
     * 投递唯一标识头名（Gitee：{@code X-Gitee-Request-Id}；Gitea：{@code X-Gitea-Delivery}）。
     *
     * <p>用于把「同一次投递」关联起来排障；取值缺失不影响业务，可留空。</p>
     */
    String webhookRequestIdHeader();

    /**
     * 校验一次投递是否真实来自托管方。
     *
     * @param rawBody <b>原始报文字节</b>。必须以字节接收，不得先转成字符串再回编 ——
     *                HMAC 是对**字节**计算的，任何字符集往返都可能改变字节序列，
     *                导致签名永远不匹配（而排查方向会被误导到「密钥配错了」）。
     * @param headers 请求头（大小写不敏感查找由实现自行处理）
     * @param secret  该项目的 Webhook 密钥（来自数据库，非配置）
     * @return 校验通过为 true；密钥为空或缺失凭证一律 false（**拒绝**而不是放行）
     */
    boolean verifyWebhook(byte[] rawBody, Map<String, String> headers, String secret);
}

"""独立验证：**用户浏览器**的授权跳转目标域，由 aioa.gitee.oauth-authorize-base-url 单独决定。

背景：曾把 web-base-url（服务端调 /oauth/token 用）同时拿去拼 /oauth/authorize，
于是「把服务端接口桩化」的部署顺手把**用户浏览器**也送进了桩 —— 用户看不到 Gitee
授权同意页，被桩直接签发一个假身份（如 gitee_dev_152）后回跳显示「绑定成功」。

判据：
  :8080 = 端到端回归接线（base-url / web-base-url / oauth-authorize-base-url 三项都指向桩）
          → authorizeHost 应为 127.0.0.1:8090，且 sandbox=true、warning 非空（必须"响"）
  :8099 = 生产默认（**未设任何** AIOA_GITEE_* 基址）
          → authorizeHost 应为 gitee.com，且 sandbox 不为 true（真实 Gitee 授权）

两个实例跑的是同一个 jar，唯一变量是配置 —— 因此本探针证明的是「配置语义」而非代码分支。
"""
import httpx

T9 = "某某智能科技有限公司"
ACC = ("znkjyf_admin", "User@123", T9)


def probe(port: int) -> None:
    c = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=25, trust_env=False)
    try:
        d = c.post("/api/v1/auth/login", json={
            "username": ACC[0], "password": ACC[1], "tenantName": ACC[2]}).json()
        if d.get("code") != 0:
            print(f"[:{port}] 登录失败 code={d.get('code')} msg={d.get('message')}")
            return
        tok = d["data"]["accessToken"]
        r = c.post("/api/v1/gitee/bind/authorize",
                   headers={"Authorization": f"Bearer {tok}"}).json()
        if r.get("code") != 0:
            print(f"[:{port}] authorize 失败 code={r.get('code')} msg={r.get('message')}")
            return
        d2 = r["data"]
        url = d2.get("url") or ""
        print(f"[:{port}] authorizeHost={d2.get('authorizeHost')!r}  sandbox={d2.get('sandbox')!r}")
        print(f"[:{port}] url={url[:120]}")
        print(f"[:{port}] warning={(d2.get('warning') or '(无)')[:100]}")
    except Exception as exc:  # noqa: BLE001
        print(f"[:{port}] 探针异常 {type(exc).__name__}: {exc}")
    finally:
        c.close()


if __name__ == "__main__":
    print("=== :8080 端到端回归接线（应有 sandbox 警告） ===")
    probe(8080)
    print("\n=== :8099 生产默认（应指向 gitee.com） ===")
    probe(8099)

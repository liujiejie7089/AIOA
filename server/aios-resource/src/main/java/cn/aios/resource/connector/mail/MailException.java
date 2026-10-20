package cn.aios.resource.connector.mail;

/**
 * 邮件收发层统一异常：所有失败收敛为带中文原因的 RuntimeException，<b>绝不</b>携带
 * 凭据（邮箱地址 / 授权码）或完整邮件正文。日志也只记录异常类型，不打印敏感内容。
 */
public class MailException extends RuntimeException {

    public MailException(String message) {
        super(message);
    }
}

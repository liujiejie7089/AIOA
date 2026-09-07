package cn.aioa.security;

import lombok.Builder;
import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 当前登录用户上下文（放入 ThreadLocal，供业务层取用）。
 */
@Data
@Builder
public class AuthUser {

    private Long userId;
    private Long tenantId;
    private String username;
    private String nickname;

    @Builder.Default
    private List<String> roles = new ArrayList<>();

    @Builder.Default
    private List<String> permissions = new ArrayList<>();

    public static AuthUser of(Long userId, Long tenantId, String username, String nickname, List<String> roles) {
        return AuthUser.builder()
                .userId(userId)
                .tenantId(tenantId)
                .username(username)
                .nickname(nickname)
                .roles(roles == null ? new ArrayList<>() : new ArrayList<>(roles))
                .permissions(new ArrayList<>())
                .build();
    }
}

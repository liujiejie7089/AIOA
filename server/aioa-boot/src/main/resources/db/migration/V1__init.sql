-- ============================================================================
-- AIOA M1 初始化 DDL（PostgreSQL）
-- 约定：所有业务表均含 id / tenant_id / created_at / updated_at / created_by / deleted_at
--       日志类表（sys_login_log、tool_invocation_log）只保留少量审计列
-- ============================================================================

-- 租户 ---------------------------------------------------------------------
CREATE TABLE sys_tenant (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   bigint       NOT NULL DEFAULT 0,
    code        varchar(64)  NOT NULL UNIQUE,
    name        varchar(128) NOT NULL,
    status      varchar(16)  NOT NULL DEFAULT 'ENABLED',
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz,
    created_by  bigint,
    deleted_at  timestamptz
);

-- 用户 / 角色 / 权限 --------------------------------------------------------
CREATE TABLE sys_user (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     bigint       NOT NULL DEFAULT 0,
    username      varchar(64)  NOT NULL UNIQUE,
    password_hash varchar(128),
    nickname      varchar(64),
    avatar        varchar(512),
    mobile        varchar(32),
    email         varchar(128),
    status        varchar(16)  NOT NULL DEFAULT 'ENABLED',
    last_login_at timestamptz,
    auth_type     varchar(16)  NOT NULL DEFAULT 'local',
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz,
    created_by    bigint,
    deleted_at    timestamptz
);

CREATE TABLE sys_role (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  bigint      NOT NULL DEFAULT 0,
    role_code  varchar(64) NOT NULL UNIQUE,
    name       varchar(128) NOT NULL,
    type       varchar(32),
    data_scope varchar(32),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    created_by bigint,
    deleted_at timestamptz
);

CREATE TABLE sys_permission (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id bigint      NOT NULL DEFAULT 0,
    perm_code varchar(128) NOT NULL UNIQUE,
    name      varchar(128) NOT NULL,
    type      varchar(32),
    parent_id bigint,
    sort      integer     NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    created_by bigint,
    deleted_at timestamptz
);

CREATE TABLE sys_user_role (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  bigint      NOT NULL DEFAULT 0,
    user_id    bigint      NOT NULL,
    role_id    bigint      NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    created_by bigint,
    deleted_at timestamptz,
    CONSTRAINT uk_sys_user_role UNIQUE (user_id, role_id)
);

CREATE TABLE sys_role_permission (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  bigint      NOT NULL DEFAULT 0,
    role_id    bigint      NOT NULL,
    perm_id    bigint      NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    created_by bigint,
    deleted_at timestamptz,
    CONSTRAINT uk_sys_role_permission UNIQUE (role_id, perm_id)
);

CREATE TABLE sys_login_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   bigint      NOT NULL DEFAULT 0,
    user_id     bigint,
    ip          varchar(64),
    ua          varchar(512),
    result      varchar(16),
    fail_reason varchar(256),
    login_at    timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- 应用注册表 ---------------------------------------------------------------
CREATE TABLE app_registry (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id      bigint       NOT NULL DEFAULT 0,
    app_code       varchar(64)  NOT NULL UNIQUE,
    name           varchar(128) NOT NULL,
    entry_url      varchar(512),
    route_prefix   varchar(128),
    host_type      varchar(16),
    icon           varchar(128),
    permission_code varchar(128),
    enabled        boolean      NOT NULL DEFAULT true,
    props          jsonb        NOT NULL DEFAULT '{}'::jsonb,
    sort           integer      NOT NULL DEFAULT 0,
    created_at     timestamptz  NOT NULL DEFAULT now(),
    updated_at     timestamptz,
    created_by     bigint,
    deleted_at     timestamptz
);

-- 会话 / 消息 / 运行 -------------------------------------------------------
CREATE TABLE chat_conversation (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     bigint       NOT NULL DEFAULT 0,
    user_id       bigint       NOT NULL,
    title         varchar(256),
    agent_code    varchar(64),
    app_code      varchar(64),
    model_ref     varchar(64),
    summary       text,
    context_turns integer      NOT NULL DEFAULT 10,
    msg_count     bigint       NOT NULL DEFAULT 0,
    status        varchar(16)  NOT NULL DEFAULT 'ACTIVE',
    last_msg_at   timestamptz,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz,
    created_by    bigint,
    deleted_at    timestamptz
);

CREATE TABLE chat_message (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id        bigint      NOT NULL DEFAULT 0,
    conversation_id  bigint      NOT NULL,
    run_id           varchar(64),
    role             varchar(16) NOT NULL,
    content          text,
    content_type     varchar(16) NOT NULL DEFAULT 'text',
    tokens           integer,
    context_snapshot jsonb,
    citations        jsonb,
    tool_calls       jsonb,
    status           varchar(16),
    seq              bigint      NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz,
    created_by       bigint,
    deleted_at       timestamptz
);
CREATE INDEX idx_chat_message_conv_seq ON chat_message (conversation_id, seq);

CREATE TABLE agent_run (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id       bigint      NOT NULL DEFAULT 0,
    run_id          varchar(64) NOT NULL UNIQUE,
    conversation_id bigint,
    user_id         bigint,
    status          varchar(16) NOT NULL,
    plan            jsonb,
    current_step    integer,
    error           text,
    tokens_in       integer     NOT NULL DEFAULT 0,
    tokens_out      integer     NOT NULL DEFAULT 0,
    started_at      timestamptz,
    ended_at        timestamptz,
    duration_ms     bigint,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz,
    created_by      bigint,
    deleted_at      timestamptz
);
CREATE INDEX idx_agent_run_conversation ON agent_run (conversation_id);

CREATE TABLE agent_run_step (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     bigint      NOT NULL DEFAULT 0,
    run_id        varchar(64) NOT NULL,
    step_seq      integer,
    step_type     varchar(32),
    agent_code    varchar(64),
    tool_code     varchar(64),
    input_masked  jsonb,
    output_digest varchar(128),
    status        varchar(16),
    duration_ms   bigint,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz,
    created_by    bigint,
    deleted_at    timestamptz
);

-- Agent / 工具 / 模型 ------------------------------------------------------
CREATE TABLE agent_definition (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     bigint      NOT NULL DEFAULT 0,
    agent_code    varchar(64) NOT NULL UNIQUE,
    name          varchar(128) NOT NULL,
    type          varchar(16),
    domain        varchar(64),
    system_prompt text,
    model_ref     varchar(64),
    context_turns integer     NOT NULL DEFAULT 10,
    max_steps     integer     NOT NULL DEFAULT 8,
    enabled       boolean     NOT NULL DEFAULT true,
    description   text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz,
    created_by    bigint,
    deleted_at    timestamptz
);

CREATE TABLE tool_system (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id       bigint       NOT NULL DEFAULT 0,
    system_code     varchar(64)  NOT NULL UNIQUE,
    name            varchar(128) NOT NULL,
    base_url        varchar(512),
    health_url      varchar(512),
    auth_type       varchar(32),
    auth_ref        varchar(256),
    timeout_ms      integer,
    circuit_breaker jsonb,
    status          varchar(16),
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz,
    created_by      bigint,
    deleted_at      timestamptz
);

CREATE TABLE tool_definition (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id           bigint       NOT NULL DEFAULT 0,
    tool_code           varchar(128) NOT NULL,
    version             varchar(32)  NOT NULL DEFAULT '1.0.0',
    name                varchar(128),
    description         text,
    domain              varchar(64),
    system_code         varchar(64),
    endpoint            varchar(512),
    http_method         varchar(16),
    input_schema        jsonb,
    output_schema       jsonb,
    risk_level          varchar(16),
    requires_approval   boolean      NOT NULL DEFAULT false,
    idempotency_required boolean     NOT NULL DEFAULT false,
    timeout_ms          integer,
    retry_policy        jsonb,
    rate_limit          varchar(64),
    auth_type           varchar(32),
    auth_ref            varchar(256),
    param_mapping       jsonb,
    response_jmespath   varchar(512),
    max_bytes           bigint,
    status              varchar(16),
    owner               varchar(64),
    created_at          timestamptz  NOT NULL DEFAULT now(),
    updated_at          timestamptz,
    created_by          bigint,
    deleted_at          timestamptz,
    CONSTRAINT uk_tool_definition UNIQUE (tool_code, version)
);

CREATE TABLE tool_permission (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  bigint       NOT NULL DEFAULT 0,
    tool_code  varchar(128) NOT NULL,
    role_code  varchar(64)  NOT NULL,
    effect     varchar(8)   NOT NULL DEFAULT 'ALLOW',
    created_at timestamptz  NOT NULL DEFAULT now(),
    updated_at timestamptz,
    created_by bigint,
    deleted_at timestamptz,
    CONSTRAINT uk_tool_permission UNIQUE (tool_code, role_code)
);

CREATE TABLE tool_invocation_log (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     bigint       NOT NULL DEFAULT 0,
    trace_id      varchar(64),
    run_id        varchar(64),
    step_id       bigint,
    tool_code     varchar(128),
    version       varchar(32),
    user_id       bigint,
    args_masked   jsonb,
    result_digest varchar(128),
    result_size   bigint,
    http_status   integer,
    duration_ms   bigint,
    approval_id   varchar(64),
    error_code    varchar(64),
    created_at    timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX idx_tool_invocation_log_code_time ON tool_invocation_log (tool_code, created_at);

-- 审计 / 模型供应商 --------------------------------------------------------
CREATE TABLE audit_log (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     bigint      NOT NULL DEFAULT 0,
    user_id       bigint,
    action        varchar(64),
    resource_type varchar(64),
    resource_id   varchar(64),
    detail        jsonb,
    "before"      jsonb,
    "after"       jsonb,
    ip            varchar(64),
    ua            varchar(512),
    result        varchar(16),
    trace_id      varchar(64),
    prev_hash     varchar(128),
    hash          varchar(128),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz,
    created_by    bigint,
    deleted_at    timestamptz
);
CREATE INDEX idx_audit_log_created_at ON audit_log (created_at);

CREATE TABLE model_provider (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   bigint       NOT NULL DEFAULT 0,
    name        varchar(64)  NOT NULL UNIQUE,
    type        varchar(32),
    base_url    varchar(512),
    models      jsonb        NOT NULL DEFAULT '[]'::jsonb,
    api_key_env varchar(128),
    enabled     boolean      NOT NULL DEFAULT true,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz,
    created_by  bigint,
    deleted_at  timestamptz
);

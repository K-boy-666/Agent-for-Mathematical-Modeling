BEGIN IMMEDIATE;

-- 1. metadata (unchanged from v1)
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

-- 2. projects (version bumped to 1.0.0)
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY
        CHECK (
            length(project_id) = 36
            AND substr(project_id, 9, 1) = '-'
            AND substr(project_id, 14, 1) = '-'
            AND substr(project_id, 15, 1) = '4'
            AND substr(project_id, 19, 1) = '-'
            AND substr(project_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND substr(project_id, 24, 1) = '-'
            AND lower(project_id) = project_id
        ),
    storage_instance_id TEXT NOT NULL
        CHECK (
            length(storage_instance_id) = 36
            AND substr(storage_instance_id, 15, 1) = '4'
            AND substr(storage_instance_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND lower(storage_instance_id) = storage_instance_id
        ),
    project_format_version TEXT NOT NULL
        CHECK (
            project_format_version IN (
                'modeling-project/0.1.0', 'modeling-project/1.0.0'
            )
        ),
    display_name TEXT NOT NULL
        CHECK (length(display_name) BETWEEN 1 AND 128),
    created_at TEXT NOT NULL
        CHECK (length(created_at) = 24 AND substr(created_at, 24, 1) = 'Z'),
    singleton INTEGER NOT NULL DEFAULT 1 UNIQUE CHECK (singleton = 1)
) STRICT;

-- 3. input_snapshots (NEW in v2)
CREATE TABLE input_snapshots (
    input_snapshot_id TEXT PRIMARY KEY
        CHECK (
            length(input_snapshot_id) = 36
            AND substr(input_snapshot_id, 9, 1) = '-'
            AND substr(input_snapshot_id, 14, 1) = '-'
            AND substr(input_snapshot_id, 15, 1) = '4'
            AND substr(input_snapshot_id, 19, 1) = '-'
            AND substr(input_snapshot_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND substr(input_snapshot_id, 24, 1) = '-'
            AND lower(input_snapshot_id) = input_snapshot_id
        ),
    canonical_input_schema_version TEXT NOT NULL,
    canonical_payload_hash TEXT NOT NULL
        CHECK (
            length(canonical_payload_hash) = 71
            AND substr(canonical_payload_hash, 1, 7) = 'sha256:'
            AND lower(canonical_payload_hash) = canonical_payload_hash
        ),
    model_snapshot_hash TEXT NOT NULL
        CHECK (
            length(model_snapshot_hash) = 71
            AND substr(model_snapshot_hash, 1, 7) = 'sha256:'
            AND lower(model_snapshot_hash) = model_snapshot_hash
        ),
    data_snapshot_references TEXT NOT NULL
        CHECK (json_valid(data_snapshot_references)),
    data_snapshot_set_hash TEXT NOT NULL
        CHECK (
            length(data_snapshot_set_hash) = 71
            AND substr(data_snapshot_set_hash, 1, 7) = 'sha256:'
            AND lower(data_snapshot_set_hash) = data_snapshot_set_hash
        ),
    created_at TEXT NOT NULL
        CHECK (length(created_at) = 24 AND substr(created_at, 24, 1) = 'Z')
) STRICT;

-- 4. experiments (version bumps + input_snapshot_id FK)
CREATE TABLE experiments (
    experiment_id TEXT PRIMARY KEY
        CHECK (
            length(experiment_id) = 36
            AND substr(experiment_id, 15, 1) = '4'
            AND substr(experiment_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND lower(experiment_id) = experiment_id
        ),
    project_id TEXT NOT NULL
        CHECK (length(project_id) = 36),
    capability_id TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    canonical_input_schema_version TEXT NOT NULL,
    canonical_payload TEXT NOT NULL CHECK (json_valid(canonical_payload)),
    canonical_payload_hash TEXT NOT NULL
        CHECK (
            length(canonical_payload_hash) = 71
            AND substr(canonical_payload_hash, 1, 7) = 'sha256:'
            AND lower(canonical_payload_hash) = canonical_payload_hash
        ),
    canonicalization_version TEXT NOT NULL
        CHECK (
            canonicalization_version IN (
                'canonical-json/0.1.0', 'canonical-json/1.0.0'
            )
        ),
    model_snapshot_hash TEXT NOT NULL
        CHECK (
            length(model_snapshot_hash) = 71
            AND substr(model_snapshot_hash, 1, 7) = 'sha256:'
            AND lower(model_snapshot_hash) = model_snapshot_hash
        ),
    data_snapshot_references TEXT NOT NULL
        CHECK (json_valid(data_snapshot_references)),
    data_snapshot_set_hash TEXT NOT NULL
        CHECK (
            length(data_snapshot_set_hash) = 71
            AND substr(data_snapshot_set_hash, 1, 7) = 'sha256:'
            AND lower(data_snapshot_set_hash) = data_snapshot_set_hash
        ),
    execution_policy TEXT NOT NULL CHECK (json_valid(execution_policy)),
    input_snapshot_id TEXT NOT NULL
        CHECK (length(input_snapshot_id) = 36),
    created_at TEXT NOT NULL
        CHECK (length(created_at) = 24 AND substr(created_at, 24, 1) = 'Z'),
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (input_snapshot_id) REFERENCES input_snapshots(input_snapshot_id)
) STRICT;

-- 5. environment_snapshots (NEW in v2)
CREATE TABLE environment_snapshots (
    environment_snapshot_id TEXT PRIMARY KEY
        CHECK (
            length(environment_snapshot_id) = 36
            AND substr(environment_snapshot_id, 9, 1) = '-'
            AND substr(environment_snapshot_id, 14, 1) = '-'
            AND substr(environment_snapshot_id, 15, 1) = '4'
            AND substr(environment_snapshot_id, 19, 1) = '-'
            AND substr(environment_snapshot_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND substr(environment_snapshot_id, 24, 1) = '-'
            AND lower(environment_snapshot_id) = environment_snapshot_id
        ),
    environment_json TEXT NOT NULL
        CHECK (json_valid(environment_json)),
    environment_hash TEXT NOT NULL
        CHECK (
            length(environment_hash) = 71
            AND substr(environment_hash, 1, 7) = 'sha256:'
            AND lower(environment_hash) = environment_hash
        ),
    created_at TEXT NOT NULL
        CHECK (length(created_at) = 24 AND substr(created_at, 24, 1) = 'Z')
) STRICT;

-- 6. attempts (added input_snapshot_id and environment_snapshot_id FKs)
CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY
        CHECK (
            length(attempt_id) = 36
            AND substr(attempt_id, 15, 1) = '4'
            AND substr(attempt_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND lower(attempt_id) = attempt_id
        ),
    experiment_id TEXT NOT NULL CHECK (length(experiment_id) = 36),
    implementation_id TEXT NOT NULL,
    implementation_version TEXT NOT NULL,
    environment_summary TEXT NOT NULL CHECK (json_valid(environment_summary)),
    randomness TEXT NOT NULL,
    seed INTEGER,
    session_id TEXT NOT NULL
        CHECK (
            length(session_id) = 36
            AND substr(session_id, 15, 1) = '4'
            AND substr(session_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND lower(session_id) = session_id
        ),
    input_snapshot_id TEXT NOT NULL
        CHECK (length(input_snapshot_id) = 36),
    environment_snapshot_id TEXT NOT NULL
        CHECK (length(environment_snapshot_id) = 36),
    status TEXT NOT NULL
        CHECK (
            status IN (
                'PENDING', 'RUNNING', 'SUCCEEDED', 'NUMERICAL_FAILURE',
                'ERRORED', 'TIMED_OUT', 'ABANDONED'
            )
        ),
    created_at TEXT NOT NULL
        CHECK (length(created_at) = 24 AND substr(created_at, 24, 1) = 'Z'),
    started_at TEXT
        CHECK (
            started_at IS NULL
            OR (length(started_at) = 24 AND substr(started_at, 24, 1) = 'Z')
        ),
    finished_at TEXT
        CHECK (
            finished_at IS NULL
            OR (length(finished_at) = 24 AND substr(finished_at, 24, 1) = 'Z')
        ),
    warnings TEXT NOT NULL CHECK (json_valid(warnings)),
    system_error TEXT CHECK (system_error IS NULL OR json_valid(system_error)),
    numerical_failure TEXT
        CHECK (numerical_failure IS NULL OR json_valid(numerical_failure)),
    terminal_reason TEXT
        CHECK (
            terminal_reason IS NULL
            OR terminal_reason IN (
                'deadline_exceeded', 'host_cancelled', 'server_recovery'
            )
        ),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id),
    FOREIGN KEY (input_snapshot_id) REFERENCES input_snapshots(input_snapshot_id),
    FOREIGN KEY (environment_snapshot_id) REFERENCES environment_snapshots(environment_snapshot_id)
) STRICT;

-- 7. result_snapshots (result_payload_json removed, result_artifact_id added)
CREATE TABLE result_snapshots (
    result_snapshot_id TEXT PRIMARY KEY
        CHECK (
            length(result_snapshot_id) = 36
            AND substr(result_snapshot_id, 15, 1) = '4'
            AND substr(result_snapshot_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND lower(result_snapshot_id) = result_snapshot_id
        ),
    attempt_id TEXT NOT NULL UNIQUE CHECK (length(attempt_id) = 36),
    result_kind TEXT NOT NULL
        CHECK (result_kind IN ('success', 'numerical_failure')),
    result_schema_version TEXT NOT NULL
        CHECK (
            result_schema_version IN (
                'modeling-result/0.1.0', 'modeling-result/1.0.0'
            )
        ),
    result_hash TEXT NOT NULL
        CHECK (
            length(result_hash) = 71
            AND substr(result_hash, 1, 7) = 'sha256:'
            AND lower(result_hash) = result_hash
        ),
    result_artifact_id TEXT NOT NULL
        CHECK (length(result_artifact_id) = 71),
    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
    FOREIGN KEY (result_artifact_id) REFERENCES artifacts(artifact_id)
) STRICT;

-- 8. artifacts (NEW in v2)
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY
        CHECK (
            length(artifact_id) = 71
            AND substr(artifact_id, 1, 7) = 'sha256:'
            AND lower(artifact_id) = artifact_id
        ),
    role TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL UNIQUE
        CHECK (
            length(sha256) = 71
            AND substr(sha256, 1, 7) = 'sha256:'
            AND lower(sha256) = sha256
        ),
    schema_id TEXT NOT NULL,
    created_at TEXT NOT NULL
        CHECK (length(created_at) = 24 AND substr(created_at, 24, 1) = 'Z')
) STRICT;

-- 9. validations (report_payload_json removed, report_artifact_id added)
CREATE TABLE validations (
    validation_id TEXT PRIMARY KEY
        CHECK (
            length(validation_id) = 36
            AND substr(validation_id, 15, 1) = '4'
            AND substr(validation_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND lower(validation_id) = validation_id
        ),
    attempt_id TEXT NOT NULL CHECK (length(attempt_id) = 36),
    expected_result_hash TEXT NOT NULL
        CHECK (
            length(expected_result_hash) = 71
            AND substr(expected_result_hash, 1, 7) = 'sha256:'
            AND lower(expected_result_hash) = expected_result_hash
        ),
    result_hash TEXT NOT NULL
        CHECK (
            length(result_hash) = 71
            AND substr(result_hash, 1, 7) = 'sha256:'
            AND lower(result_hash) = result_hash
        ),
    validator_id TEXT NOT NULL,
    validator_implementation_id TEXT NOT NULL,
    validator_implementation_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    policy TEXT NOT NULL CHECK (json_valid(policy)),
    policy_hash TEXT NOT NULL
        CHECK (
            length(policy_hash) = 71
            AND substr(policy_hash, 1, 7) = 'sha256:'
            AND lower(policy_hash) = policy_hash
        ),
    status TEXT NOT NULL
        CHECK (
            status IN (
                'PENDING', 'RUNNING', 'SUCCEEDED', 'ERRORED',
                'TIMED_OUT', 'ABANDONED'
            )
        ),
    created_at TEXT NOT NULL
        CHECK (length(created_at) = 24 AND substr(created_at, 24, 1) = 'Z'),
    started_at TEXT
        CHECK (
            started_at IS NULL
            OR (length(started_at) = 24 AND substr(started_at, 24, 1) = 'Z')
        ),
    finished_at TEXT
        CHECK (
            finished_at IS NULL
            OR (length(finished_at) = 24 AND substr(finished_at, 24, 1) = 'Z')
        ),
    outcome TEXT
        CHECK (outcome IS NULL OR outcome IN ('PASSED', 'FAILED', 'INCONCLUSIVE')),
    metrics TEXT CHECK (metrics IS NULL OR json_valid(metrics)),
    validation_report_hash TEXT
        CHECK (
            validation_report_hash IS NULL
            OR (
                length(validation_report_hash) = 71
                AND substr(validation_report_hash, 1, 7) = 'sha256:'
                AND lower(validation_report_hash) = validation_report_hash
            )
        ),
    report_artifact_id TEXT
        CHECK (
            report_artifact_id IS NULL
            OR (length(report_artifact_id) = 71 AND report_artifact_id LIKE 'sha256:%')
        ),
    operational_error TEXT
        CHECK (operational_error IS NULL OR json_valid(operational_error)),
    terminal_reason TEXT
        CHECK (
            terminal_reason IS NULL
            OR terminal_reason IN (
                'deadline_exceeded', 'host_cancelled', 'server_recovery'
            )
        ),
    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
    FOREIGN KEY (report_artifact_id) REFERENCES artifacts(artifact_id)
) STRICT;

-- 10. idempotency_records (unchanged from v1)
CREATE TABLE idempotency_records (
    scope_id TEXT NOT NULL
        CHECK (
            length(scope_id) = 36
            AND substr(scope_id, 15, 1) = '4'
            AND substr(scope_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND lower(scope_id) = scope_id
        ),
    tool_name TEXT NOT NULL,
    operation_id TEXT NOT NULL
        CHECK (
            length(operation_id) = 36
            AND substr(operation_id, 15, 1) = '4'
            AND substr(operation_id, 20, 1) IN ('8', '9', 'a', 'b')
            AND lower(operation_id) = operation_id
        ),
    canonical_request_hash TEXT NOT NULL
        CHECK (
            length(canonical_request_hash) = 71
            AND substr(canonical_request_hash, 1, 7) = 'sha256:'
            AND lower(canonical_request_hash) = canonical_request_hash
        ),
    status TEXT NOT NULL CHECK (status IN ('IN_PROGRESS', 'COMPLETED')),
    result_entity_references TEXT NOT NULL
        CHECK (json_valid(result_entity_references)),
    UNIQUE (scope_id, tool_name, operation_id)
) STRICT;

PRAGMA user_version=2;
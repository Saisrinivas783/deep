import boto3
import json
from botocore.exceptions import ClientError

# =============================================================================
# CONFIG — edit these values only
# =============================================================================

GUARDRAIL_NAME      = "my-guardrail"
BEDROCK_ACCOUNT_ID  = "<BEDROCK_ACCOUNT_ID>"
BEDROCK_ROLE_NAME   = "<BedrockCrossAccountRole>"
REGION              = "us-east-1"

# =============================================================================
# STEP 1: Authenticate — assume cross-account role
# =============================================================================

def get_bedrock_client():
    sts_client = boto3.client("sts")

    assumed_role = sts_client.assume_role(
        RoleArn=f"arn:aws:iam::{BEDROCK_ACCOUNT_ID}:role/{BEDROCK_ROLE_NAME}",
        RoleSessionName="SageMakerGuardrailSession"
    )
    credentials = assumed_role["Credentials"]

    client = boto3.client(
        "bedrock",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"]
    )
    print(f"✅ Authenticated — Bedrock client ready ({REGION})")
    return client

# =============================================================================
# STEP 2: Resolve guardrail ID by fixed name
# =============================================================================

def get_guardrail_id_by_name(client, name):
    """
    Lists all guardrails (no identifier = one DRAFT entry per guardrail).
    Matches by fixed name and returns the guardrail ID.
    """
    paginator = client.get_paginator("list_guardrails")
    for page in paginator.paginate():
        for g in page.get("guardrails", []):
            if g["name"] == name and g["version"] == "DRAFT":
                return g["guardrailId"]
    return None

# =============================================================================
# STEP 3: Create guardrail (idempotent — skips if name already exists)
# =============================================================================

def create_guardrail(client, name):
    guardrail_id = get_guardrail_id_by_name(client, name)

    if guardrail_id:
        print(f"⚠️  Guardrail '{name}' already exists — skipping creation.")
        print(f"   ID: {guardrail_id}")
        return guardrail_id

    response = client.create_guardrail(
        name=name,
        description="Guardrail to filter harmful content",
        blockedInputMessaging="Sorry, I cannot process this request.",
        blockedOutputsMessaging="Sorry, I cannot return this response.",

        contentPolicyConfig={
            "filtersConfig": [
                {"type": "HATE",          "inputStrength": "HIGH",   "outputStrength": "HIGH"},
                {"type": "VIOLENCE",      "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"},
                {"type": "SEXUAL",        "inputStrength": "HIGH",   "outputStrength": "HIGH"},
                {"type": "INSULTS",       "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"},
                {"type": "MISCONDUCT",    "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"},
                {"type": "PROMPT_ATTACK", "inputStrength": "HIGH",   "outputStrength": "NONE"},
            ]
        },
        topicPolicyConfig={
            "topicsConfig": [
                {
                    "name": "Financial Advice",
                    "definition": "Providing specific financial or investment advice to users.",
                    "examples": [
                        "Should I buy Tesla stock?",
                        "What crypto should I invest in?"
                    ],
                    "type": "DENY"
                }
            ]
        },
        sensitiveInformationPolicyConfig={
            "piiEntitiesConfig": [
                {"type": "EMAIL", "action": "ANONYMIZE"},
                {"type": "PHONE", "action": "ANONYMIZE"},
                {"type": "SSN",   "action": "BLOCK"},
            ]
        },
        wordPolicyConfig={
            "wordsConfig": [
                {"text": "competitor_name"},
                {"text": "badword"}
            ],
            "managedWordListsConfig": [{"type": "PROFANITY"}]
        },
        tags=[
            {"key": "Environment", "value": "production"},
            {"key": "CreatedBy",   "value": "sagemaker"}
        ]
    )

    guardrail_id = response["guardrailId"]
    print(f"✅ Guardrail '{name}' created:")
    print(f"   ID:      {guardrail_id}")
    print(f"   ARN:     {response['guardrailArn']}")
    print(f"   Version: {response['version']}")
    return guardrail_id

# =============================================================================
# STEP 4: Ensure version 1 exists (idempotent — skips if already published)
# =============================================================================

def ensure_version_1(client, guardrail_id, guardrail_name):
    """
    list_guardrails with identifier returns all versions (DRAFT, 1, 2, ...).
    Creates version 1 only if it doesn't already exist.
    """
    response = client.list_guardrails(guardrailIdentifier=guardrail_id)
    existing_versions = [
        g["version"] for g in response.get("guardrails", [])
        if g["name"] == guardrail_name
        and g["id"] == guardrail_id
        and g["version"] != "DRAFT"
    ]

    print(f"   Existing numbered versions: {existing_versions}")

    if "1" in existing_versions:
        print(f"⚠️  Version 1 already exists for '{guardrail_name}' ({guardrail_id}) — skipping.")
    else:
        ver_response = client.create_guardrail_version(
            guardrailIdentifier=guardrail_id,
            description="First production version"
        )
        print(f"✅ Version {ver_response['version']} published for '{guardrail_name}' ({guardrail_id})")

# =============================================================================
# STEP 5: Update guardrail DRAFT
# =============================================================================

def update_guardrail(client, guardrail_id, guardrail_name):
    """
    Updates the DRAFT version of the guardrail.
    Numbered versions are immutable — only DRAFT can be edited.
    Modify the policy configs below to reflect your changes.
    """
    response = client.update_guardrail(
        guardrailIdentifier=guardrail_id,
        name=guardrail_name,                   # required even if unchanged
        description="Guardrail to filter harmful content — updated",
        blockedInputMessaging="Sorry, I cannot process this request.",
        blockedOutputsMessaging="Sorry, I cannot return this response.",

        contentPolicyConfig={
            "filtersConfig": [
                {"type": "HATE",          "inputStrength": "HIGH",   "outputStrength": "HIGH"},
                {"type": "VIOLENCE",      "inputStrength": "HIGH",   "outputStrength": "HIGH"},   # updated
                {"type": "SEXUAL",        "inputStrength": "HIGH",   "outputStrength": "HIGH"},
                {"type": "INSULTS",       "inputStrength": "HIGH",   "outputStrength": "HIGH"},   # updated
                {"type": "MISCONDUCT",    "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"},
                {"type": "PROMPT_ATTACK", "inputStrength": "HIGH",   "outputStrength": "NONE"},
            ]
        },
        topicPolicyConfig={
            "topicsConfig": [
                {
                    "name": "Financial Advice",
                    "definition": "Providing specific financial or investment advice to users.",
                    "examples": [
                        "Should I buy Tesla stock?",
                        "What crypto should I invest in?"
                    ],
                    "type": "DENY"
                }
            ]
        },
        sensitiveInformationPolicyConfig={
            "piiEntitiesConfig": [
                {"type": "EMAIL", "action": "ANONYMIZE"},
                {"type": "PHONE", "action": "ANONYMIZE"},
                {"type": "SSN",   "action": "BLOCK"},
            ]
        },
        wordPolicyConfig={
            "wordsConfig": [
                {"text": "competitor_name"},
                {"text": "badword"}
            ],
            "managedWordListsConfig": [{"type": "PROFANITY"}]
        },
    )

    print(f"✅ Guardrail '{guardrail_name}' DRAFT updated:")
    print(f"   ID:      {response['guardrailId']}")
    print(f"   Version: {response['version']}")   # always DRAFT
    return response

# =============================================================================
# STEP 6: Publish new version from updated DRAFT (auto-increments)
# =============================================================================

def publish_new_version(client, guardrail_id, guardrail_name, description=None):
    """
    Snapshots the current DRAFT into the next numbered version.
    Bedrock auto-increments: version 1 → 2 → 3, etc.
    """
    response = client.list_guardrails(guardrailIdentifier=guardrail_id)
    existing_versions = sorted([
        int(g["version"]) for g in response.get("guardrails", [])
        if g["name"] == guardrail_name
        and g["id"] == guardrail_id
        and g["version"] != "DRAFT"
    ])

    next_version = (existing_versions[-1] + 1) if existing_versions else 1
    print(f"   Current versions: {existing_versions} → publishing version {next_version}")

    ver_response = client.create_guardrail_version(
        guardrailIdentifier=guardrail_id,
        description=description or f"Version {next_version}"
    )

    print(f"✅ Version {ver_response['version']} published for '{guardrail_name}' ({guardrail_id})")
    return ver_response

# =============================================================================
# MAIN — controls which steps run
# =============================================================================

if __name__ == "__main__":

    # --- Authenticate ---
    bedrock_client = get_bedrock_client()

    # --- Create (idempotent) + publish version 1 ---
    guardrail_id = create_guardrail(bedrock_client, GUARDRAIL_NAME)
    ensure_version_1(bedrock_client, guardrail_id, GUARDRAIL_NAME)

    # --- To update + publish a new version, uncomment below ---
    # update_guardrail(bedrock_client, guardrail_id, GUARDRAIL_NAME)
    # publish_new_version(
    #     bedrock_client,
    #     guardrail_id,
    #     GUARDRAIL_NAME,
    #     description="Increased violence and insults strength to HIGH"
    # )

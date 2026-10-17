# Local warrants in five commands

Read a real report, then attempt to read another report outside the warrant.
Tenuo blocks that second call before the file-reading handler runs. No account,
model API key, Docker or server is needed.

This example uses the unreleased common CLI and `TenuoTool.local` SDK changes.
Install the matching Tenuo source checkout into your environment first:

```bash
pip install -e '/path/to/tenuo/tenuo-python[langchain]'
```

From this directory:

```bash
tenuo-cli init --dev
tenuo-cli warrant issue --template report.yaml --holder agent --out .tenuo/report.warrant
python run_demo.py
tenuo-cli warrant show --file .tenuo/report.warrant
tenuo-cli warrant verify --file .tenuo/report.warrant
```

Expected output includes:

```text
ALLOW: Weekly service report: all three scheduled backup checks completed successfully.
DENY: private report: ...
Handler calls: 1 (weekly only)
```

`report.yaml` is the reusable template. `request.yaml` describes the same scope
as an ad-hoc request, including its recipient. To issue from that request:

```bash
tenuo-cli warrant issue --request request.yaml
tenuo-cli warrant list
```

The signed artifact is generated during setup, not checked in with an expired
timestamp. `show` decodes tools, limits, approval gates and expiry; `verify`
separately checks trust, the full chain and revocations. Copy the full ID from
`warrant list` to revoke it:

```bash
tenuo-cli revocations add --id tnu_wrt_REPLACE_WITH_LISTED_ID
```

An issued warrant grants authority until it expires or is revoked. Issuing a
replacement does not edit or revoke the old one. Changing YAML does not change
an already signed warrant. Revocation reaches a verifier through the updated
signed list; the CLI does not distribute files across machines.

`init --dev` handles local keys automatically. It is a development setup: keys
under one OS user are not isolated. A deployed agent receives its own key,
warrant and public verification data, while controller and approver private
keys remain outside its runtime. This example is an in-process guardrail;
arbitrary Python code could bypass the wrapper and read files directly.

For agents helping with the example, use the matching SDK's
`skills/tenuo-warrant/SKILL.md` and `skills/tenuo-agent-authorization/SKILL.md`.
Keep human-authored templates and requests in YAML, use the SDK's parser, never
mint from inside a tool, and test denial before the handler rather than merely
catching a configuration error.

Run its test with `pip install pytest && python -m pytest test_demo.py -q`.

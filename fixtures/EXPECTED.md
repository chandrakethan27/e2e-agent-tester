# Fixture expectations

Known-answer projects for checking the whole system end to end.

| Fixture | Command | Expected outcome |
|---|---|---|
| vuln-flask | `/evaluate fixtures/vuln-flask --depth quick` | project_type `api-service`; runtime `running` (generated Dockerfile); confirmed critical/high **security** finding for SQL injection in `/search` with a curl repro; secret finding for `API_SECRET` (gitleaks); dependency CVEs for flask/werkzeug 2.2.2 (osv); false claims "safe against injection" and "1000 req/s" flagged; critical **compliance** finding for missing license; verdict **Hold** with security and/or license gates |
| tiny-cli | `/evaluate fixtures/tiny-cli --depth quick --profile radar` | project_type `cli`; runtime `running` (toolchain image or generated Dockerfile); suite-runner 3/3 passing; README claims pass; no critical/high findings; verdict **Adopt** or **Trial** |
| broken-build | `/evaluate fixtures/broken-build --depth quick` | runtime `failed`; critical **functional** finding "Project could not be built or run" citing the npm 404 for `e2eat-this-package-does-not-exist`; squad = security, architecture, viability only; verdict **Hold** with gate "project could not be built or run" |

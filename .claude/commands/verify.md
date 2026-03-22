---
description: "PR 전 종합 검증: 테스트, 린트, 포맷, 디버그 잔재, 변경 범위"
---

Run the following checks sequentially and report results as a pass/fail table:

1. **Test + Coverage**: `uv run pytest --cov=forge --cov-report=term-missing -q`
2. **Lint**: `ruff check forge/`
3. **Format**: `ruff format --check forge/`
4. **Debug print audit**: `grep -rn "print(" forge/ --include="*.py"` (flag any non-logging prints)
5. **Change scope**: `git diff --stat`

After all checks complete, output a summary table:

| Check | Status |
|-------|--------|
| Tests | PASS/FAIL |
| Coverage | XX% |
| Lint | PASS/FAIL |
| Format | PASS/FAIL |
| Debug prints | CLEAN / N found |
| Changes | N files changed |

**Ready for PR: YES / NO**

If any check fails, list the specific issues that need fixing.

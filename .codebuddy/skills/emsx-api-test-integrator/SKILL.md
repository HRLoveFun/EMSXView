---
name: emsx-api-test-integrator
description: This skill should be used when modifying EMSX-related program functions or troubleshooting EMSX API issues. It provides a structured workflow for diagnosing problems, testing code examples from documentation, validating fixes, and integrating working solutions into the project.
---

# EMSX API Test and Integrate Skill

## Purpose

This skill provides a structured workflow for troubleshooting EMSX API issues, testing code examples from documentation, validating fixes, and integrating successful tests into the project codebase.

## When to Use

Use this skill when:
- Modifying EMSX-related program functions (connection, orders, routes, subscriptions)
- Troubleshooting EMSX API connection or functionality issues
- Diagnosing port occupation, session timeout, or service errors
- Testing EMSX API code examples from documentation
- Validating API integration patterns before production use
- Incorporating documented code samples into the project
- Verifying connection, order management, or subscription workflows

## Workflow

### Step 1: Read Quick Reference

Load the quick reference documentation to identify the relevant API section:

```
Read: docs/reference/EMSX-API-Quick-Reference.md
```

Locate the section matching the user's request (e.g., Order Management, Route Management, Subscriptions).

### Step 2: Find Detailed Documentation

Using the quick reference as a guide, locate the corresponding detailed section:

```
Read: docs/reference/EMSX-API-Complete-Guide.md
```

Search for the specific topic using the table of contents or section headers. Extract the complete code examples and configuration details.

### Step 3: Analyze Code Examples

Identify all code blocks in the relevant section. For each code example:
- Note the programming language (Python, Java, .NET, C++)
- Identify required dependencies (blpapi library, etc.)
- Extract configuration parameters (service name, host, port)
- Identify placeholder values that need real data

### Step 4: Prepare Test Environment

Before running tests:
1. Verify Bloomberg API library is installed (`blpapi` for Python)
2. Check connection parameters:
   - Service: `//blp/emapisvc_beta` (UAT) or `//blp/emapisvc` (Production)
   - Host: typically `localhost`
   - Port: typically `8194`
3. Ensure Bloomberg terminal access or Trading API Server is available
4. Create a test script based on the documented example

### Step 5: Execute Tests

Run the test code:

```bash
# For Python tests
python test_script.py
```

For each test:
- Capture the full output
- Note any errors or exceptions
- Record successful responses
- Document any required modifications

### Step 6: Handle Test Results

**Critical: Always close the test program after completion to prevent port occupation.**

After each test execution, ensure proper cleanup:
1. Stop the Bloomberg API session: `session.stop()`
2. Release all resources and close connections
3. Verify the port (default 8194) is released
4. Terminate the test program/process completely

**If test succeeds:**
1. Clean up the code (remove debug prints, add proper error handling)
2. Ensure session cleanup code is included in the final implementation
3. Add the code to the appropriate location in the project:
   - Connection logic → `app/lib/emsx/`
   - API wrappers → `app/lib/emsx/`
   - Test files → `app/lib/emsx/__tests__/`
4. Add inline documentation referencing the source documentation
5. Update any integration points
6. Close the test program and verify port release

**If test fails:**
1. Check connection parameters and credentials
2. Verify Bloomberg service availability
3. Review error messages against documentation FAQ
4. Document the failure and attempt alternative approaches from the guide
5. **Always close the test program even on failure** to prevent port occupation
6. Report blocking issues to user with specific error details

### Step 7: Integration

When integrating successful code:
- Follow existing project patterns and conventions
- Add proper TypeScript types if converting from Python examples
- Ensure error handling matches project standards
- Add logging consistent with other EMSX modules
- Update relevant exports in index files

## File Locations

- Quick Reference: `docs/reference/EMSX-API-Quick-Reference.md`
- Complete Guide: `docs/reference/EMSX-API-Complete-Guide.md`
- EMSX Library Code: `app/lib/emsx/`
- EMSX Tests: `app/lib/emsx/__tests__/`
- Backend Python: `emsx-backend/`

## Testing Guidelines

- Always test in UAT/Beta environment first (`//blp/emapisvc_beta`)
- Use small order quantities for testing
- Include timeout handling (recommended: 5000ms for requests)
- Implement proper session cleanup in all tests
- Never commit test credentials or real account information

## Common Patterns

### Session Setup
```python
sessionOptions = blpapi.SessionOptions()
sessionOptions.setServerHost("localhost")
sessionOptions.setServerPort(8194)
session = blpapi.Session(sessionOptions)
```

### Service Opening
```python
SERVICE = "//blp/emapisvc_beta"  # UAT environment
if not session.openService(SERVICE):
    raise Exception("Failed to open service")
```

### Request with Correlation ID
```python
request = service.createRequest("CreateOrder")
request.set("EMSX_TICKER", "TEST US Equity")
cid = blpapi.CorrelationId(1)
session.sendRequest(request, correlationId=cid)
```

### Session Cleanup (Required)
```python
# Always stop the session to release port 8194
try:
    session.stop()
    print("Session stopped successfully, port released")
except Exception as e:
    print(f"Error stopping session: {e}")
finally:
    # Ensure program terminates completely
    sys.exit(0)
```

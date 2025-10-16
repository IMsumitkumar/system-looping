#!/bin/bash
#
# Run all test scripts in order
# Exit on first failure
#

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================================================"
echo -e "${YELLOW}Running All Test Scripts${NC}"
echo "========================================================================"
echo ""

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Array of test scripts in order
tests=(
    "01_test_race_conditions.py"
    "02_test_state_machine.py"
    "03_test_security.py"
    "04_test_database_performance.py"
    "05_test_approval_flow.py"
    "06_test_event_bus.py"
    "07_test_timeout_manager.py"
    "08_test_workflow_engine.py"
    "09_test_integration.py"
    "10_test_load.py"
)

total=${#tests[@]}
passed=0
failed=0

# Run each test
for test in "${tests[@]}"; do
    echo -e "${YELLOW}Running: $test${NC}"

    if python "$SCRIPT_DIR/$test"; then
        ((passed++))
        echo -e "${GREEN}✓ PASSED${NC}: $test"
    else
        ((failed++))
        echo -e "${RED}✗ FAILED${NC}: $test"
        echo ""
        echo "========================================================================"
        echo -e "${RED}Test suite FAILED at: $test${NC}"
        echo "========================================================================"
        exit 1
    fi

    echo ""
done

# Summary
echo "========================================================================"
if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✓ ALL TESTS PASSED${NC}: $passed/$total"
else
    echo -e "${RED}✗ SOME TESTS FAILED${NC}: $passed passed, $failed failed"
fi
echo "========================================================================"

exit $failed

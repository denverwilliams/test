#!/usr/bin/env python3
"""
Local test script for helm.parse.py
This simulates the Azure DevOps pipeline environment for testing purposes.
"""

import os
import sys

# Set mock environment variables for testing
# You should adjust these values based on your actual setup
os.environ['SYSTEM_ACCESSTOKEN'] = 'test-token-not-used-locally'
os.environ['SYSTEM_PULLREQUEST_TARGETBRANCH'] = 'main'  # Change this to your target branch
os.environ['SYSTEM_TEAMFOUNDATIONCOLLECTIONURI'] = 'https://dev.azure.com/yourorg/'
os.environ['SYSTEM_TEAMPROJECT'] = 'yourproject'
os.environ['BUILD_REPOSITORY_ID'] = 'test-repo-id'
os.environ['SYSTEM_PULLREQUEST_PULLREQUESTID'] = '123'
os.environ['BUILD_BUILDID'] = '456'
os.environ['BUILD_BUILDNUMBER'] = '20250107.1'
os.environ['SYSTEM_JOBID'] = 'test-job-id'

# Flag to enable dry-run mode (won't post to ADO)
DRY_RUN = True

print("=" * 60)
print("LOCAL TEST MODE")
print("=" * 60)
print(f"Target Branch: {os.environ['SYSTEM_PULLREQUEST_TARGETBRANCH']}")
print(f"Dry Run: {DRY_RUN}")
print("=" * 60)
print()

# Monkey-patch the post_pr_comment function to avoid actually posting
if DRY_RUN:
    import helm_parse

    original_post = helm_parse.post_pr_comment

    def mock_post_pr_comment(comment_text, status, access_token, pr_info):
        print("\n" + "=" * 60)
        print("DRY RUN - Would post the following comment:")
        print("=" * 60)
        print(f"Status: {status}")
        print("-" * 60)
        print(comment_text)
        print("=" * 60)
        return True

    helm_parse.post_pr_comment = mock_post_pr_comment

# Import and run the main script
import helm_parse

if __name__ == "__main__":
    try:
        helm_parse.main()
    except Exception as e:
        print(f"\nError during test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

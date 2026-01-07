import os
import json
import base64
import requests
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from urllib.parse import quote


def run_command(cmd, cwd=None, capture_output=True):
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            check=False
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        print(f"Error running command '{cmd}': {e}")
        return 1, "", str(e)


def find_helm_charts(base_path="."):
    """Find all Helm charts in the repository (excluding subcharts)."""
    charts = []
    for chart_yaml in Path(base_path).rglob("Chart.yaml"):
        # Exclude charts in the 'charts' subdirectory (dependencies)
        if "/charts/" not in str(chart_yaml) and "\\charts\\" not in str(chart_yaml):
            chart_dir = chart_yaml.parent
            charts.append(chart_dir)
    return charts


def template_chart(chart_path, output_dir):
    """Template a Helm chart and save the output."""
    chart_name = chart_path.name
    output_file = output_dir / f"{chart_name}.yaml"

    cmd = f"helm template {chart_name} {chart_path}"
    returncode, stdout, stderr = run_command(cmd)

    if returncode != 0:
        print(f"Warning: Failed to template chart {chart_name}")
        print(f"Error: {stderr}")
        output_file.write_text(f"# Error templating chart\n# {stderr}")
        return False

    output_file.write_text(stdout)
    return True


def generate_diff(target_file, pr_file, chart_name):
    """Generate a unified diff between target and PR templates."""
    cmd = f"diff -u {target_file} {pr_file}"
    returncode, stdout, stderr = run_command(cmd)

    # diff returns 0 if no changes, 1 if changes found, 2 if error
    if returncode == 0:
        return None  # No changes
    elif returncode == 1:
        return stdout  # Changes found
    else:
        print(f"Error generating diff for {chart_name}: {stderr}")
        return None


def format_diff_comment(diffs, build_info):
    """Format the diff information into a markdown comment."""
    if not diffs:
        comment = "**Helm Charts Summary:**\n\n"
        comment += "No changes detected! :white_check_mark:\n\n"
        comment += "All Helm charts template to the same output as the target branch.\n\n"
        status = "closed"
    else:
        comment = "**Helm Charts Changes Detected:**\n\n"
        comment += f"Found changes in {len(diffs)} chart(s):\n\n"

        for chart_name, diff_content in diffs.items():
            comment += f"## Chart: `{chart_name}`\n\n"

            # Limit diff size to avoid huge comments
            lines = diff_content.split('\n')
            max_lines = 200

            if len(lines) > max_lines:
                truncated_diff = '\n'.join(lines[:max_lines])
                comment += f"```diff\n{truncated_diff}\n```\n"
                comment += f"_... (diff truncated, showing first {max_lines} of {len(lines)} lines)_\n\n"
            else:
                comment += f"```diff\n{diff_content}\n```\n\n"

        status = "active"

    # Add build link
    url_prefix = f"{build_info['collection_uri']}{build_info['project']}"
    link_url = quote(
        f"{url_prefix}/_build/results?buildId={build_info['build_id']}&view=logs&j={build_info['job_id']}",
        safe=":/?&="
    )
    comment += f"\nFor detailed logs, see [Pipeline {build_info['build_number']} logs]({link_url})\n"

    return comment, status


def post_pr_comment(comment_text, status, access_token, pr_info):
    """Post a comment to the Azure DevOps PR."""
    url_prefix = f"{pr_info['collection_uri']}{pr_info['project']}"
    url = (
        f"{url_prefix}/_apis/git/repositories/{pr_info['repo_id']}/"
        f"pullRequests/{pr_info['pr_id']}/threads?api-version=7.1"
    )

    request = {
        "comments": [
            {
                "content": comment_text,
                "commentType": "text"
            }
        ],
        "status": status
    }

    basic_encoded = base64.b64encode(f":{access_token}".encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {basic_encoded}",
        "Content-Type": "application/json"
    }

    request_body = json.dumps(request)

    print(f"Posting comment to {url}")
    try:
        response = requests.post(url, headers=headers, data=request_body, verify=False)

        if response.status_code == 200:
            print("Comment posted successfully.")
            return True
        else:
            print(f"Failed to post comment. Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"Exception posting comment: {e}")
        return False


def main():
    print("======= Starting Helm Template Diff Process =======")

    # Get environment variables
    try:
        access_token = os.environ['SYSTEM_ACCESSTOKEN']
        target_branch = os.environ['SYSTEM_PULLREQUEST_TARGETBRANCH']

        # Remove refs/heads/ prefix if present
        if target_branch.startswith('refs/heads/'):
            target_branch = target_branch.replace('refs/heads/', '')

        pr_info = {
            'collection_uri': os.environ['SYSTEM_TEAMFOUNDATIONCOLLECTIONURI'],
            'project': os.environ['SYSTEM_TEAMPROJECT'],
            'repo_id': os.environ['BUILD_REPOSITORY_ID'],
            'pr_id': os.environ['SYSTEM_PULLREQUEST_PULLREQUESTID']
        }

        build_info = {
            'collection_uri': os.environ['SYSTEM_TEAMFOUNDATIONCOLLECTIONURI'],
            'project': os.environ['SYSTEM_TEAMPROJECT'],
            'build_id': os.environ['BUILD_BUILDID'],
            'build_number': os.environ['BUILD_BUILDNUMBER'],
            'job_id': os.environ['SYSTEM_JOBID']
        }

    except KeyError as e:
        print(f"ERROR: Missing required environment variable: {e}")
        sys.exit(1)

    # Create temporary directories
    temp_dir = Path(tempfile.mkdtemp())
    pr_templates_dir = temp_dir / "pr-templates"
    target_templates_dir = temp_dir / "target-templates"
    pr_templates_dir.mkdir(parents=True, exist_ok=True)
    target_templates_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Find all Helm charts
        print("\n======= Finding Helm Charts =======")
        charts = find_helm_charts()
        print(f"Found {len(charts)} chart(s):")
        for chart in charts:
            print(f"  - {chart}")

        if not charts:
            print("No Helm charts found in repository!")
            sys.exit(0)

        # Template PR branch charts
        print("\n======= Templating PR Branch Charts =======")
        for chart_path in charts:
            print(f"Templating {chart_path.name}...")
            template_chart(chart_path, pr_templates_dir)

        # Checkout target branch
        print(f"\n======= Checking out target branch: {target_branch} =======")
        returncode, stdout, stderr = run_command(f"git fetch origin {target_branch}")
        if returncode != 0:
            print(f"Error fetching target branch: {stderr}")
            sys.exit(1)

        returncode, stdout, stderr = run_command(f"git checkout origin/{target_branch}")
        if returncode != 0:
            print(f"Error checking out target branch: {stderr}")
            sys.exit(1)

        # Template target branch charts
        print("\n======= Templating Target Branch Charts =======")
        for chart_path in charts:
            chart_name = chart_path.name

            # Check if chart exists in target branch
            if not chart_path.exists():
                print(f"Chart {chart_name} does not exist in target branch (new chart)")
                output_file = target_templates_dir / f"{chart_name}.yaml"
                output_file.write_text("# Chart added in PR\n")
            else:
                print(f"Templating {chart_name}...")
                template_chart(chart_path, target_templates_dir)

        # Switch back to PR branch
        print("\n======= Returning to PR branch =======")
        returncode, stdout, stderr = run_command("git checkout -")
        if returncode != 0:
            print(f"Warning: Could not switch back to PR branch: {stderr}")

        # Generate diffs
        print("\n======= Generating Diffs =======")
        diffs = {}

        for pr_template in pr_templates_dir.glob("*.yaml"):
            chart_name = pr_template.stem
            target_template = target_templates_dir / pr_template.name

            # Create target template if it doesn't exist (chart deleted in PR)
            if not target_template.exists():
                target_template.write_text("# Chart deleted in PR\n")

            print(f"Comparing {chart_name}...")
            diff_content = generate_diff(target_template, pr_template, chart_name)

            if diff_content:
                diffs[chart_name] = diff_content
                print(f"  Changes detected in {chart_name}")
            else:
                print(f"  No changes in {chart_name}")

        # Format and post comment
        print("\n======= Formatting PR Comment =======")
        comment_text, status = format_diff_comment(diffs, build_info)

        print("\n======= Posting Comment to PR =======")
        success = post_pr_comment(comment_text, status, access_token, pr_info)

        if not success:
            sys.exit(1)

        print("\n======= Process Complete =======")

    finally:
        # Cleanup
        print(f"\nCleaning up temporary directory: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Structural check of template.yaml, runnable without AWS.

Parses the SAM template with PyYAML (using a loader that tolerates
the !Ref, !Sub, and !GetAtt intrinsic tags) and asserts the shape
this project depends on: exactly one resource, the guard function,
on Python 3.12 with the right handler; an API event for POST /guard;
an IAM action list of exactly one action,
comprehend:DetectPiiEntities; and the ApiUrl output.

What this check cannot prove: it does not run the SAM transform and
it is not a deployment, so it cannot see transform errors or
dependency cycles between resources. A sibling project learned that
the hard way, with a template that passed a check like this one and
still failed twice in CloudFormation. This template is kept to one
function, one event, and one permission partly so there is less for
a deploy to trip over, but only a real deployment settles it.

Usage: python3 validate_template.py
"""

import os
import sys

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))


class SamLoader(yaml.SafeLoader):
    pass


def _unknown_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return {tag_suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {tag_suffix: loader.construct_sequence(node)}
    return {tag_suffix: loader.construct_mapping(node)}


SamLoader.add_multi_constructor("!", _unknown_tag)


def main():
    with open(os.path.join(ROOT, "template.yaml"), encoding="utf-8") as handle:
        template = yaml.load(handle, Loader=SamLoader)

    assert template["Transform"] == "AWS::Serverless-2016-10-31"
    resources = template["Resources"]
    assert set(resources) == {"GuardFunction"}, (
        f"expected exactly one resource, found {sorted(resources)}"
    )
    guard_fn = resources["GuardFunction"]
    assert guard_fn["Type"] == "AWS::Serverless::Function"
    print("resource ok: GuardFunction (AWS::Serverless::Function)")

    props = guard_fn["Properties"]
    assert props["Handler"] == "handler.lambda_handler"
    runtime = template["Globals"]["Function"]["Runtime"]
    assert runtime == "python3.12", runtime
    print(f"function ok: handler.lambda_handler on {runtime}")

    event = props["Events"]["Guard"]
    assert event["Type"] == "Api"
    assert event["Properties"]["Path"] == "/guard"
    assert event["Properties"]["Method"] == "post"
    print("event ok: POST /guard")

    actions = []
    for policy in props["Policies"]:
        for statement in policy["Statement"]:
            actions.extend(statement["Action"])
    assert actions == ["comprehend:DetectPiiEntities"], (
        f"guard function must hold exactly one permission, found {actions}"
    )
    print(f"iam ok: GuardFunction: {actions}")

    assert "ApiUrl" in template["Outputs"]
    print("TEMPLATE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

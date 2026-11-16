"""Run stage 4 on classification contexts.

    python -m idp.stages.classifier --input <file|dir>

LLM settings come from the environment (config/settings.py) and can be overridden here. Exit status is
1 when any document failed to load or validate, 0 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from config.settings import ClassifierSettings
from idp.models.llm import create_provider
from idp.stages.classifier.llm_fallback import FileCache
from idp.stages.classifier.service import Classifier, classify_uri
from idp.stages.classifier.taxonomy import load_taxonomy
from idp.storage.artifacts import list_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify table and paragraph units (stage 4).")
    parser.add_argument("--input", action="append", required=True, help="Classification-context JSON file or directory (repeatable)")
    parser.add_argument("--rules-dir", type=Path, help="Override IDP_RULES_DIR")
    parser.add_argument("--provider", help="Override IDP_LLM_PROVIDER (none, bedrock, gemini, module:Class)")
    parser.add_argument("--model", help="Override IDP_LLM_MODEL")
    parser.add_argument("--cache-dir", type=Path, help="Override IDP_LLM_CACHE_DIR")
    args = parser.parse_args(argv)

    settings = ClassifierSettings.from_env()
    settings = replace(
        settings,
        rules_dir=args.rules_dir or settings.rules_dir,
        llm_provider=args.provider or settings.llm_provider,
        llm_model=args.model or settings.llm_model,
        llm_cache_dir=args.cache_dir or settings.llm_cache_dir,
    )
    taxonomy = load_taxonomy(settings.rules_dir)
    provider = create_provider(settings.llm_provider, settings.llm_model, **settings.provider_options())
    cache = FileCache(settings.llm_cache_dir) if settings.llm_cache_dir else None
    classifier = Classifier(taxonomy, provider, cache)

    inputs = [uri for item in args.input for uri in list_json(item)]
    failures = 0
    for uri in inputs:
        try:
            target, result = classify_uri(classifier, uri)
        except Exception as error:  # one bad document must not stop the batch
            failures += 1
            print(f"ERROR {uri}: {type(error).__name__}: {error}", file=sys.stderr)
            continue
        print(f"{uri} -> {target}: {result.summary.units} units, {result.summary.by_status}, escalated {result.summary.escalated}")
    print(f"done: {len(inputs) - failures}/{len(inputs)} documents classified")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

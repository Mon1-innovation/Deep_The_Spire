from __future__ import annotations
import argparse
from pathlib import Path
from .pipeline import convert_keyframes
from .codex import CATALOG_TYPES, CodexCatalog, DEFAULT_BASE_URL
from .provider import provider_from_environment

def main() -> None:
    parser = argparse.ArgumentParser(description="将《杀戮尖塔 2》关键帧转换为结构化日志")
    parser.add_argument("input", help="某一局已有关键帧所在的目录")
    parser.add_argument("--provider", choices=["mock", "openai-compatible"], default="openai-compatible")
    parser.add_argument("--run-id", help="对局 ID；默认使用输入目录名称")
    parser.add_argument("--patch")
    parser.add_argument("--output-folder", default="logs", help="在对局目录内创建的输出文件夹名称，默认 logs")
    parser.add_argument("--no-codex", action="store_true", help="禁用 Spire Codex 实体名称归一化")
    parser.add_argument("--codex-base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--codex-lang", default="zhs", help="Spire Codex 语言，默认 zhs")
    parser.add_argument("--codex-channel", choices=["stable", "beta"], default="stable")
    parser.add_argument("--codex-version", help="请求 Spire Codex 的指定数据版本；接口不提供时会标记为未验证")
    args = parser.parse_args()
    input_path = Path(args.input)
    run_id = args.run_id or input_path.name
    output_dir = input_path / args.output_folder
    output_path = output_dir / f"{run_id}.json"
    cache_dir = output_dir / "cache"
    catalogs = {}
    if not args.no_codex and args.provider != "mock":
        for entity_type in CATALOG_TYPES:
            catalog_cache = output_dir / "codex_cache" / f"{entity_type}_{args.codex_lang}_{args.codex_channel}_{args.codex_version or 'latest'}.json"
            try:
                catalogs[entity_type] = CodexCatalog.load(catalog_cache, base_url=args.codex_base_url, lang=args.codex_lang, channel=args.codex_channel, version=args.codex_version, entity_type=entity_type)
                print(f"codex[{entity_type}]: {catalogs[entity_type].source}")
            except Exception as error:
                print(f"warning: Spire Codex {entity_type} catalog unavailable; detected names will be kept without IDs: {error}")
    result = convert_keyframes(input_path, output_path, provider_from_environment(args.provider), run_id, args.patch, cache_dir, catalogs=catalogs)
    print(f"wrote {len(result['observations'])} observations and {len(result['events'])} events")
    print(f"json: {output_path}")
    print(f"jsonl: {output_path.with_suffix('.jsonl')}")
    print(f"markdown: {output_path.with_suffix('.md')}")
    print(f"cache: {cache_dir}")

if __name__ == "__main__":
    main()


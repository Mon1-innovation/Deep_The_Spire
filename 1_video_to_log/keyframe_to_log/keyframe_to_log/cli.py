from __future__ import annotations
import argparse
from pathlib import Path
from .pipeline import convert_keyframes
from .provider import provider_from_environment

def main() -> None:
    parser = argparse.ArgumentParser(description="将《杀戮尖塔 2》关键帧转换为结构化日志")
    parser.add_argument("input", help="某一局已有关键帧所在的目录")
    parser.add_argument("--provider", choices=["mock", "openai-compatible"], default="openai-compatible")
    parser.add_argument("--run-id", help="对局 ID；默认使用输入目录名称")
    parser.add_argument("--patch")
    parser.add_argument("--output-folder", default="logs", help="在对局目录内创建的输出文件夹名称，默认 logs")
    args = parser.parse_args()
    input_path = Path(args.input)
    run_id = args.run_id or input_path.name
    output_dir = input_path / args.output_folder
    output_path = output_dir / f"{run_id}.json"
    cache_dir = output_dir / "cache"
    result = convert_keyframes(input_path, output_path, provider_from_environment(args.provider), run_id, args.patch, cache_dir)
    print(f"wrote {len(result['observations'])} observations and {len(result['events'])} events")
    print(f"json: {output_path}")
    print(f"jsonl: {output_path.with_suffix('.jsonl')}")
    print(f"markdown: {output_path.with_suffix('.md')}")
    print(f"cache: {cache_dir}")

if __name__ == "__main__":
    main()


"""
batch_make_videos.py — Mass produce YouTube Shorts from a list of topics.

Usage:
    python batch_make_videos.py topics.txt
    python batch_make_videos.py topics.txt --output "G:\My Drive\YouTube Shorts"
    python batch_make_videos.py --generate 50  (auto-generate 50 viral topics)
"""
import sys, os, json, time, argparse
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from make_video import make_video


def generate_viral_topics(count: int = 50) -> list:
    """Use Gemini to generate viral 'What if' topics."""
    import google.generativeai as genai
    genai.configure(api_key=config.GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    resp = model.generate_content(f"""Generate {count} unique viral YouTube Shorts topics in the "What if" or 
    mind-blowing science/nature format. These should be dramatic, visual, and grab attention.

    Return ONLY a JSON array of strings, nothing else. Example:
    ["What if the Moon crashed into Earth?", "What if humans could breathe underwater?"]
    
    Make them diverse: space, ocean, physics, biology, history, weather, geology.
    Each topic should be something that would make amazing cinematic visuals.
    """)

    text = resp.text.strip()
    if "```" in text:
        text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


def batch_produce(topics: list, output_dir: str = None):
    """Run the pipeline for each topic."""
    total = len(topics)
    results = {"success": [], "failed": []}
    
    print(f"\n{'='*60}", flush=True)
    print(f"  BATCH PRODUCTION: {total} videos", flush=True)
    print(f"{'='*60}\n", flush=True)

    for i, topic in enumerate(topics, 1):
        print(f"\n[{i}/{total}] {topic}", flush=True)
        print("-" * 50, flush=True)
        try:
            path = make_video(topic, num_scenes=5, output_dir=output_dir)
            results["success"].append({"topic": topic, "path": str(path)})
        except Exception as e:
            print(f"   [FAILED] {e}", flush=True)
            results["failed"].append({"topic": topic, "error": str(e)})

    # Summary
    print(f"\n{'='*60}", flush=True)
    print(f"  BATCH COMPLETE", flush=True)
    print(f"  Success: {len(results['success'])}/{total}", flush=True)
    print(f"  Failed:  {len(results['failed'])}/{total}", flush=True)
    print(f"{'='*60}\n", flush=True)

    # Save report
    report_path = config.PROJECTS_DIR / "batch_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Report saved: {report_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch YouTube Shorts Factory")
    parser.add_argument("topics_file", nargs="?", help="Text file with one topic per line")
    parser.add_argument("--generate", type=int, help="Auto-generate N viral topics")
    parser.add_argument("--output", type=str, help="Output directory (default: Google Drive)")
    args = parser.parse_args()

    if args.generate:
        print(f"Generating {args.generate} viral topics...", flush=True)
        topics = generate_viral_topics(args.generate)
        # Save for reference
        with open(config.BASE_DIR / "topics.txt", "w", encoding="utf-8") as f:
            for t in topics:
                f.write(t + "\n")
        print(f"Saved to topics.txt", flush=True)
    elif args.topics_file:
        with open(args.topics_file, "r", encoding="utf-8") as f:
            topics = [line.strip() for line in f if line.strip()]
    else:
        parser.print_help()
        sys.exit(1)

    batch_produce(topics, args.output)

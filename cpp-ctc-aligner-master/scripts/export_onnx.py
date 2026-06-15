import argparse
from pathlib import Path

import torch
from transformers import AutoModelForCTC, AutoTokenizer


def export_onnx(model_dir: str, out_dir: str) -> None:
    # Ensure logs are printable on Windows consoles.
    import io
    import sys

    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    model = AutoModelForCTC.from_pretrained(model_dir, torch_dtype=torch.float32).cpu().eval()
    tokenizer = AutoTokenizer.from_pretrained(model_dir)

    # Save vocab.json (needed for <blank>/<pad>/letters mapping).
    # Some tokenizers don't expose vocab_file attribute. For local dirs, use repo file.
    model_dir_path = Path(model_dir)
    vocab_dst = out / "vocab.json"
    if model_dir_path.exists() and model_dir_path.is_dir():
        vocab_src = model_dir_path / "vocab.json"
        vocab_dst.write_bytes(vocab_src.read_bytes())
    else:
        # Fall back to tokenizer vocab dict.
        import json

        vocab_dst.write_text(
            json.dumps(tokenizer.get_vocab(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    onnx_path = out / "model.onnx"

    # Input: float32[batch, samples]
    # Output: float32[batch, frames, vocab_without_star]
    dummy = torch.zeros((1, 16000), dtype=torch.float32)

    torch.onnx.export(
        model,
        args=(dummy,),
        f=str(onnx_path),
        input_names=["input_values"],
        output_names=["logits"],
        dynamic_axes={
            "input_values": {0: "batch", 1: "samples"},
            "logits": {0: "batch", 1: "frames"},
        },
        opset_version=18,
    )

    print(f"Wrote: {onnx_path}")
    print(f"Wrote: {vocab_dst}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="Local model directory or HF model id")
    ap.add_argument("--out", required=True, help="Output directory")
    args = ap.parse_args()

    export_onnx(args.model, args.out)


if __name__ == "__main__":
    main()

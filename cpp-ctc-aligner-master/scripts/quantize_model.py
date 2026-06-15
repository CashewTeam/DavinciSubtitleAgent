#!/usr/bin/env python3
"""Quantize the ONNX model to INT8 for faster inference and smaller size."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Quantize ONNX model to INT8")
    parser.add_argument(
        "--input",
        type=str,
        default="models/mms-300m-1130-forced-aligner/model.onnx",
        help="Input ONNX model path",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output quantized model path (default: input_int8.onnx)",
    )
    parser.add_argument(
        "--quant-type",
        type=str,
        choices=["int8", "uint8"],
        default="int8",
        help="Quantization type (default: int8)",
    )
    args = parser.parse_args()

    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError:
        print("Error: onnxruntime not installed.")
        print("Run: pip install onnxruntime")
        return 1

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input model not found: {input_path}")
        return 1

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_stem(input_path.stem + "_int8")

    weight_type = QuantType.QInt8 if args.quant_type == "int8" else QuantType.QUInt8

    print(f"Input model:  {input_path}")
    print(f"Output model: {output_path}")
    print(f"Quant type:   {args.quant_type}")
    print()

    input_size = input_path.stat().st_size
    data_file = input_path.with_suffix(".onnx.data")
    if data_file.exists():
        input_size += data_file.stat().st_size
    print(f"Input size:   {input_size / 1024 / 1024:.1f} MB")
    print()

    # Wav2Vec2 uses weight normalization for Conv layers, which means
    # conv weights are computed dynamically. We need to exclude Conv
    # from quantization and only quantize MatMul/Gemm (attention layers).
    print("Quantizing to INT8 (MatMul/Gemm only, excluding Conv)...")
    print("  Note: Conv layers use weight normalization and cannot be quantized directly.")
    print()

    quantize_dynamic(
        model_input=str(input_path),
        model_output=str(output_path),
        weight_type=weight_type,
        op_types_to_quantize=["MatMul", "Gemm"],  # Only quantize these ops
    )

    output_size = output_path.stat().st_size
    out_data_file = output_path.with_suffix(".onnx.data")
    if out_data_file.exists():
        output_size += out_data_file.stat().st_size

    print(f"Output size:  {output_size / 1024 / 1024:.1f} MB")
    print(f"Compression:  {input_size / output_size:.1f}x")
    print()
    print(f"Done! Quantized model saved to: {output_path}")
    return 0


if __name__ == "__main__":
    exit(main())

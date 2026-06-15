#include "json_io.h"
#include <nlohmann/json.hpp>
#include <fstream>
#include <sstream>
#include <stdexcept>

using json = nlohmann::json;

namespace {

std::string read_all_text(const std::filesystem::path& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Failed to open: " + path.string());
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

SrtSegment parse_segment_object(const json& obj, int default_index) {
    SrtSegment seg;
    seg.index = obj.value("index", default_index);
    seg.start_sec = obj.value("start", 0.0);
    seg.end_sec = obj.value("end", 0.0);
    // text field is required per spec
    if (!obj.contains("text")) {
        throw std::runtime_error("Segment missing required 'text' field at index " + std::to_string(default_index));
    }
    seg.text = obj["text"].get<std::string>();
    // score field is ignored on input (we compute our own)
    return seg;
}

} // namespace

std::vector<SrtSegment> parse_json_input(const std::string& content) {
    json j = json::parse(content);
    std::vector<SrtSegment> segments;

    // Direct array format: [...]
    if (j.is_array()) {
        int index = 1;
        for (const auto& item : j) {
            segments.push_back(parse_segment_object(item, index++));
        }
        return segments;
    }

    // Object format: {"segments": [...]}
    if (j.is_object()) {
        if (!j.contains("segments")) {
            throw std::runtime_error("JSON object missing 'segments' field");
        }
        int index = 1;
        for (const auto& item : j["segments"]) {
            segments.push_back(parse_segment_object(item, index++));
        }
        return segments;
    }

    throw std::runtime_error("Invalid JSON: expected array or object");
}

std::vector<SrtSegment> read_json_input(const std::filesystem::path& path) {
    return parse_json_input(read_all_text(path));
}

std::string format_json_output(
    const std::vector<SrtSegment>& segments,
    double processing_time) {

    json j;
    j["segments"] = json::array();

    for (const auto& seg : segments) {
        json seg_obj;
        seg_obj["index"] = seg.index;
        seg_obj["start"] = seg.start_sec;
        seg_obj["end"] = seg.end_sec;
        seg_obj["text"] = seg.text;
        seg_obj["score"] = seg.score;
        j["segments"].push_back(seg_obj);
    }

    j["metadata"]["count"] = segments.size();
    j["metadata"]["processing_time"] = processing_time;

    return j.dump(2) + "\n";
}

void write_json_output(
    const std::filesystem::path& path,
    const std::vector<SrtSegment>& segments,
    double processing_time) {

    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Failed to open for writing: " + path.string());
    f << format_json_output(segments, processing_time);
}

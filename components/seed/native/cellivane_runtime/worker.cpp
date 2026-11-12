// Cellivane owns the bounded generation loop; pinned libllama owns tensors/KV.
// This CPU worker does not implement paging, MTP, shared KV, or weight changes.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#include <bcrypt.h>
#include <fcntl.h>
#include <io.h>

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "llama.h"
#include "json.hpp"

using json = nlohmann::json;
using Clock = std::chrono::steady_clock;
static constexpr const char * ENGINE_COMMIT = "d81235049384534c167caea52b85a694f6103d14";
static constexpr size_t MAX_LINE = 65536;
static constexpr size_t MAX_CONTENT = 16384;

struct Failure : std::runtime_error { using std::runtime_error::runtime_error; };
static void require(bool ok, const char * code) { if (!ok) throw Failure(code); }
static double seconds(Clock::time_point start) { return std::chrono::duration<double>(Clock::now() - start).count(); }

static bool utf8(const std::string & value) {
    if (value.empty()) return true;
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), nullptr, 0) > 0;
}
static std::string narrow(const std::wstring & value) {
    int count = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    require(count > 0, "path-encoding");
    std::string result(count, '\0');
    require(WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), result.data(), count, nullptr, nullptr) == count, "path-encoding");
    return result;
}
static json peak_memory() {
    PROCESS_MEMORY_COUNTERS counters{};
    counters.cb = sizeof(counters);
    if (!GetProcessMemoryInfo(GetCurrentProcess(), &counters, sizeof(counters))) return nullptr;
    return static_cast<uint64_t>(counters.PeakWorkingSetSize);
}
static std::string sha256(const std::string & value) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    require(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0, "prompt-hash");
    unsigned char digest[32]{};
    NTSTATUS status = BCryptHash(algorithm, nullptr, 0,
        reinterpret_cast<PUCHAR>(const_cast<char *>(value.data())), static_cast<ULONG>(value.size()), digest, sizeof(digest));
    BCryptCloseAlgorithmProvider(algorithm, 0);
    require(status >= 0, "prompt-hash");
    static const char * digits = "0123456789abcdef";
    std::string result;
    for (unsigned char byte : digest) { result += digits[byte >> 4]; result += digits[byte & 15]; }
    return result;
}
static void emit(const json & value) {
    std::cout << value.dump(-1, ' ', false, json::error_handler_t::strict) << '\n' << std::flush;
    require(std::cout.good(), "stdout-write");
}
static bool exact(const json & value, std::initializer_list<const char *> keys) {
    if (!value.is_object() || value.size() != keys.size()) return false;
    for (const char * key : keys) if (!value.contains(key)) return false;
    return true;
}
static int64_t integer(const json & value, int64_t low, int64_t high, const char * code) {
    require(value.is_number_integer() && !value.is_boolean(), code);
    if (value.is_number_unsigned()) require(value.get<uint64_t>() <= static_cast<uint64_t>(high), code);
    int64_t number = value.get<int64_t>();
    require(number >= low && number <= high, code);
    return number;
}
static json strict_json(const std::string & line) {
    require(utf8(line), "input-invalid-utf8");
    std::vector<std::set<std::string>> objects;
    auto callback = [&objects](int depth, json::parse_event_t event, json & parsed) {
        require(depth <= 16, "json-depth");
        if (event == json::parse_event_t::object_start) objects.emplace_back();
        else if (event == json::parse_event_t::key) {
            require(!objects.empty() && objects.back().insert(parsed.get<std::string>()).second, "json-duplicate-key");
        } else if (event == json::parse_event_t::object_end) objects.pop_back();
        return true;
    };
    try { return json::parse(line, callback); }
    catch (const Failure &) { throw; }
    catch (...) { throw Failure("invalid-json"); }
}
struct Message { std::string role; std::string content; };
struct Command { int64_t id; bool shutdown; int max_tokens = 0; std::vector<Message> messages; };
static Command command(const json & value) {
    require(value.is_object() && value.contains("id") && value.contains("op"), "command-shape");
    Command result{integer(value.at("id"), 0, INT64_MAX, "command-id"), false};
    require(value.at("op").is_string(), "command-op");
    std::string op = value.at("op").get<std::string>();
    if (op == "shutdown") {
        require(exact(value, {"id", "op"}), "shutdown-shape");
        result.shutdown = true;
        return result;
    }
    require(op == "generate" && exact(value, {"id", "op", "messages", "max_tokens"}), "generate-shape");
    result.max_tokens = static_cast<int>(integer(value.at("max_tokens"), 1, 64, "max-tokens"));
    const auto & messages = value.at("messages");
    require(messages.is_array() && messages.size() >= 1 && messages.size() <= 32, "messages-count");
    size_t bytes = 0;
    bool user = false;
    for (const auto & message : messages) {
        require(exact(message, {"role", "content"}) && message.at("role").is_string() && message.at("content").is_string(), "message-shape");
        Message item{message.at("role").get<std::string>(), message.at("content").get<std::string>()};
        require(item.role == "system" || item.role == "user" || item.role == "assistant", "message-role");
        require(!item.content.empty() && utf8(item.content), "message-content");
        for (unsigned char c : item.content) require(c >= 32 || c == '\n' || c == '\t', "message-control");
        bytes += item.content.size();
        require(bytes <= MAX_CONTENT, "messages-bytes");
        user = user || item.role == "user";
        result.messages.push_back(std::move(item));
    }
    require(user, "user-required");
    return result;
}
enum class Read { Line, Eof, Truncated };
static Read line_read(std::string & result) {
    result.clear();
    for (;;) {
        int c = std::cin.get();
        if (c == EOF) return result.empty() ? Read::Eof : Read::Truncated;
        if (c == '\n') { if (!result.empty() && result.back() == '\r') result.pop_back(); return Read::Line; }
        require(result.size() < MAX_LINE, "line-too-large");
        result.push_back(static_cast<char>(c));
    }
}
template<class F> struct Finally {
    F fn; bool active = true;
    explicit Finally(F value) : fn(std::move(value)) {}
    ~Finally() { if (active) fn(); }
    void run() { if (active) { active = false; fn(); } }
    Finally(const Finally &) = delete;
};
template<class F> Finally<F> finally(F value) { return Finally<F>(std::move(value)); }

struct Options {
    std::filesystem::path engine, model;
    int threads = 4, context = 512, batch = 128;
    bool selftest = false;
};
static int option_int(const std::wstring & value, int low, int high) {
    std::string text = narrow(value);
    int result = 0;
    auto parsed = std::from_chars(text.data(), text.data() + text.size(), result);
    require(parsed.ec == std::errc() && parsed.ptr == text.data() + text.size() && result >= low && result <= high, "argument-range");
    return result;
}
static Options options(int argc, wchar_t ** argv) {
    Options result;
    std::set<std::wstring> seen;
    for (int i = 1; i < argc; ++i) {
        std::wstring key(argv[i]);
        require(seen.insert(key).second, "argument-duplicate");
        if (key == L"--protocol-selftest") { result.selftest = true; continue; }
        require(i + 1 < argc, "argument-value");
        std::wstring value(argv[++i]);
        if (key == L"--engine-dir") result.engine = value;
        else if (key == L"--model") result.model = value;
        else if (key == L"--threads") result.threads = option_int(value, 1, 64);
        else if (key == L"--context") result.context = option_int(value, 128, 2048);
        else if (key == L"--batch") result.batch = option_int(value, 1, 512);
        else throw Failure("argument-unknown");
    }
    require(result.batch <= result.context, "batch-context");
    if (!result.selftest) {
        require(result.engine.is_absolute() && std::filesystem::is_directory(result.engine), "engine-directory");
        require(result.model.is_absolute() && std::filesystem::is_regular_file(result.model), "model-file");
        result.engine = std::filesystem::canonical(result.engine);
        result.model = std::filesystem::canonical(result.model);
    } else require(result.engine.empty() && result.model.empty(), "selftest-no-model");
    return result;
}

class Engine {
    std::vector<HMODULE> modules;
    DLL_DIRECTORY_COOKIE cookie = nullptr;
    bool initialized = false;
    llama_model * model = nullptr;
    uint64_t generation = 0;
    std::string template_mode_ = "libllama-chat-template";
    template<class T> T symbol(const char * name) {
        for (auto module : modules) if (auto address = GetProcAddress(module, name)) return reinterpret_cast<T>(address);
        throw Failure("engine-symbol");
    }
#define API(name) decltype(&::name) p_##name = nullptr
    API(llama_model_default_params); API(llama_context_default_params);
    API(llama_backend_init); API(llama_backend_free); API(llama_model_load_from_file); API(llama_model_free);
    API(llama_init_from_model); API(llama_free); API(llama_model_get_vocab); API(llama_model_chat_template);
    API(llama_model_has_encoder); API(llama_model_has_decoder); API(llama_n_ctx); API(llama_tokenize);
    API(llama_model_meta_val_str);
    API(llama_token_to_piece); API(llama_vocab_is_eog); API(llama_chat_apply_template);
    API(llama_sampler_init_greedy); API(llama_sampler_free); API(llama_sampler_sample);
    API(llama_synchronize); API(llama_decode); API(llama_batch_init); API(llama_batch_free); API(llama_log_set);
    API(ggml_log_set); API(ggml_backend_load_all_from_path); API(ggml_backend_dev_count); API(ggml_backend_dev_get); API(ggml_backend_dev_type);
#undef API
    static void log(enum ggml_log_level, const char * text, void *) { if (text) { std::fputs(text, stderr); std::fflush(stderr); } }
    std::string piece(const llama_vocab * vocab, llama_token token) {
        std::vector<char> buffer(256);
        int count = p_llama_token_to_piece(vocab, token, buffer.data(), static_cast<int>(buffer.size()), 0, false);
        if (count < 0) {
            require(count != INT32_MIN && -count <= 65536, "token-piece-size");
            buffer.resize(static_cast<size_t>(-count));
            count = p_llama_token_to_piece(vocab, token, buffer.data(), static_cast<int>(buffer.size()), 0, false);
        }
        require(count >= 0 && static_cast<size_t>(count) <= buffer.size(), "token-piece");
        return std::string(buffer.data(), static_cast<size_t>(count));
    }
public:
    Engine() = default;
    Engine(const Engine &) = delete;
    ~Engine() { close(); }
    const std::string & template_mode() const { return template_mode_; }
    void close() noexcept {
        if (model) { p_llama_model_free(model); model = nullptr; }
        if (initialized) { p_llama_backend_free(); initialized = false; }
        for (auto it = modules.rbegin(); it != modules.rend(); ++it) FreeLibrary(*it);
        modules.clear();
        if (cookie) { RemoveDllDirectory(cookie); cookie = nullptr; }
    }
    double open(const Options & config) {
        auto start = Clock::now();
        require(SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32 | LOAD_LIBRARY_SEARCH_USER_DIRS) != 0, "dll-search-policy");
        cookie = AddDllDirectory(config.engine.c_str());
        require(cookie != nullptr, "dll-directory");
        for (const auto * name : {L"ggml-base.dll", L"ggml.dll", L"llama.dll"}) {
            HMODULE module = LoadLibraryExW((config.engine / name).c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32 | LOAD_LIBRARY_SEARCH_USER_DIRS);
            require(module != nullptr, "engine-dll-load");
            modules.push_back(module);
        }
#define BIND(name) p_##name = symbol<decltype(p_##name)>(#name)
        BIND(llama_model_default_params); BIND(llama_context_default_params); BIND(llama_backend_init); BIND(llama_backend_free);
        BIND(llama_model_load_from_file); BIND(llama_model_free); BIND(llama_init_from_model); BIND(llama_free);
        BIND(llama_model_get_vocab); BIND(llama_model_chat_template); BIND(llama_model_has_encoder); BIND(llama_model_has_decoder);
        BIND(llama_model_meta_val_str);
        BIND(llama_n_ctx); BIND(llama_tokenize); BIND(llama_token_to_piece); BIND(llama_vocab_is_eog); BIND(llama_chat_apply_template);
        BIND(llama_sampler_init_greedy); BIND(llama_sampler_free); BIND(llama_sampler_sample); BIND(llama_synchronize);
        BIND(llama_decode); BIND(llama_batch_init); BIND(llama_batch_free); BIND(llama_log_set);
        BIND(ggml_log_set); BIND(ggml_backend_load_all_from_path); BIND(ggml_backend_dev_count); BIND(ggml_backend_dev_get); BIND(ggml_backend_dev_type);
#undef BIND
        p_llama_log_set(log, nullptr); p_ggml_log_set(log, nullptr);
        p_ggml_backend_load_all_from_path(narrow(config.engine.wstring()).c_str());
        require(p_ggml_backend_dev_count() > 0, "cpu-backend-missing");
        for (size_t i = 0; i < p_ggml_backend_dev_count(); ++i)
            require(p_ggml_backend_dev_type(p_ggml_backend_dev_get(i)) == GGML_BACKEND_DEVICE_TYPE_CPU, "non-cpu-backend");
        p_llama_backend_init(); initialized = true;
        auto params = p_llama_model_default_params();
        params.n_gpu_layers = 0; params.split_mode = LLAMA_SPLIT_MODE_NONE;
        params.load_mode = LLAMA_LOAD_MODE_NONE; params.lazy_mode = LLAMA_LAZY_MODE_OFF;
        params.use_extra_bufts = false; params.load_mtp = false;
        params.vocab_only = false; params.no_alloc = false;
        model = p_llama_model_load_from_file(narrow(config.model.wstring()).c_str(), params);
        require(model != nullptr, "model-load");
        require(!p_llama_model_has_encoder(model) && p_llama_model_has_decoder(model), "decoder-only-required");
        require(p_llama_model_chat_template(model, nullptr) != nullptr, "chat-template-missing");
        char architecture[128]{};
        int architecture_size = p_llama_model_meta_val_str(model, "general.architecture", architecture, sizeof(architecture));
        require(architecture_size > 0 && architecture_size < sizeof(architecture), "model-architecture");
        if (std::string(architecture) == "qwen3") {
            // b11429's C helper renders Qwen3 as ChatML and ignores the Jinja
            // enable_thinking parameter. Select this explicit Qwen3-only input
            // rendering; never remove tags or alter a generated answer.
            std::string tmpl(p_llama_model_chat_template(model, nullptr));
            require(tmpl.find("enable_thinking") != std::string::npos && tmpl.find("<think>") != std::string::npos &&
                    tmpl.find("<|im_start|>") != std::string::npos, "qwen3-template-unrecognized");
            template_mode_ = "qwen3-nonthinking";
        }
        return seconds(start);
    }
    json generate(const Command & request, const Options & config) {
        auto started = Clock::now();
        require(generation < static_cast<uint64_t>(INT64_MAX), "generation-overflow");
        uint64_t identity = ++generation;
        std::vector<llama_chat_message> messages;
        for (const auto & item : request.messages) messages.push_back({item.role.c_str(), item.content.c_str()});
        const char * tmpl = p_llama_model_chat_template(model, nullptr);
        std::vector<char> prompt(32768);
        int count = p_llama_chat_apply_template(tmpl, messages.data(), messages.size(), true, prompt.data(), static_cast<int>(prompt.size()));
        require(count >= 0 && count <= 262144, "chat-template-unsupported");
        if (static_cast<size_t>(count) > prompt.size()) {
            prompt.resize(static_cast<size_t>(count));
            count = p_llama_chat_apply_template(tmpl, messages.data(), messages.size(), true, prompt.data(), static_cast<int>(prompt.size()));
        }
        require(count > 0 && static_cast<size_t>(count) <= prompt.size(), "chat-template");
        std::string rendered(prompt.data(), static_cast<size_t>(count));
        if (template_mode_ == "qwen3-nonthinking") {
            const std::string suffix = "<|im_start|>assistant\n";
            require(rendered.size() >= suffix.size() && rendered.compare(rendered.size() - suffix.size(), suffix.size(), suffix) == 0,
                    "qwen3-template-prefix");
            rendered += "<think>\n\n</think>\n\n";
        }
        std::string rendered_sha256 = sha256(rendered);
        const llama_vocab * vocab = p_llama_model_get_vocab(model);
        require(vocab != nullptr, "model-vocab");
        std::vector<llama_token> prompt_tokens(static_cast<size_t>(config.context) + 1);
        int n = p_llama_tokenize(vocab, rendered.data(), static_cast<int>(rendered.size()), prompt_tokens.data(), static_cast<int>(prompt_tokens.size()), true, true);
        require(n > 0 && n <= config.context - request.max_tokens, "prompt-context-limit");
        prompt_tokens.resize(static_cast<size_t>(n));
        auto params = p_llama_context_default_params();
        params.n_ctx = config.context; params.n_batch = config.batch; params.n_ubatch = config.batch;
        params.n_seq_max = 1; params.n_threads = config.threads; params.n_threads_batch = config.threads;
        params.offload_kqv = false; params.op_offload = false; params.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_DISABLED;
        llama_context * context = p_llama_init_from_model(model, params);
        require(context != nullptr, "context-init");
        auto context_guard = finally([&] { p_llama_free(context); });
        require(p_llama_n_ctx(context) >= static_cast<uint32_t>(n + request.max_tokens), "actual-context-limit");
        llama_sampler * sampler = p_llama_sampler_init_greedy();
        require(sampler != nullptr, "sampler-init");
        auto sampler_guard = finally([&] { p_llama_sampler_free(sampler); });
        llama_batch batch = p_llama_batch_init(config.batch, 0, 1);
        require(batch.token && batch.pos && batch.n_seq_id && batch.seq_id && batch.logits, "batch-init");
        auto batch_guard = finally([&] { p_llama_batch_free(batch); });
        auto prefill = Clock::now();
        for (int offset = 0; offset < n; offset += config.batch) {
            batch.n_tokens = std::min(config.batch, n - offset);
            for (int i = 0; i < batch.n_tokens; ++i) {
                batch.token[i] = prompt_tokens[offset + i]; batch.pos[i] = offset + i;
                batch.n_seq_id[i] = 1; batch.seq_id[i][0] = 0;
                batch.logits[i] = (offset + i == n - 1);
            }
            require(p_llama_decode(context, batch) == 0, "prefill-decode");
        }
        p_llama_synchronize(context);
        double prefill_s = seconds(prefill);
        auto decode = Clock::now();
        std::vector<llama_token> tokens;
        std::string text, finish = "length";
        for (int i = 0; i < request.max_tokens; ++i) {
            llama_token token = p_llama_sampler_sample(sampler, context, -1); // sample includes accept.
            require(token >= 0, "sample-token");
            if (p_llama_vocab_is_eog(vocab, token)) { finish = "stop"; break; }
            tokens.push_back(token); text += piece(vocab, token);
            require(text.size() <= 262144, "output-bytes-limit");
            if (i + 1 == request.max_tokens) break;
            batch.n_tokens = 1; batch.token[0] = token; batch.pos[0] = n + i;
            batch.n_seq_id[0] = 1; batch.seq_id[0][0] = 0; batch.logits[0] = 1;
            require(p_llama_decode(context, batch) == 0, "token-decode");
        }
        p_llama_synchronize(context);
        double decode_s = seconds(decode);
        require(utf8(text), "output-invalid-utf8");
        batch_guard.run(); sampler_guard.run(); context_guard.run();
        return {{"kind", "result"}, {"id", request.id}, {"text", text}, {"tokens", tokens},
                {"prompt_tokens", n}, {"completion_tokens", tokens.size()}, {"finish_reason", finish},
                {"prefill_s", prefill_s}, {"decode_s", decode_s}, {"elapsed_s", seconds(started)},
                {"context_id", identity}, {"sampler_id", identity},
                {"rendered_prompt_sha256", rendered_sha256},
                {"context_disposed", true}, {"sampler_disposed", true}, {"peak_working_set_bytes", peak_memory()}};
    }
};

int wmain(int argc, wchar_t ** argv) {
    _setmode(_fileno(stdin), _O_BINARY); _setmode(_fileno(stdout), _O_BINARY);
    json current_id = nullptr;
    try {
        Options config = options(argc, argv);
        Engine engine;
        double load_s = config.selftest ? 0.0 : engine.open(config);
        emit({{"kind", "ready"}, {"protocol", 1}, {"engine_commit", ENGINE_COMMIT},
              {"threads", config.threads}, {"context_tokens", config.context}, {"gpu_layers", 0}, {"model_load_s", load_s},
              {"template_mode", config.selftest ? "protocol-selftest" : engine.template_mode()}});
        std::string line;
        for (;;) {
            current_id = nullptr;
            Read state = line_read(line);
            require(state == Read::Line, state == Read::Eof ? "shutdown-required" : "truncated-line");
            json value = strict_json(line);
            if (value.is_object() && value.contains("id")) {
                try { current_id = integer(value.at("id"), 0, INT64_MAX, "command-id"); } catch (...) {}
            }
            Command request = command(value);
            if (request.shutdown) {
                engine.close();
                emit({{"kind", "stopped"}, {"id", request.id}, {"model_disposed", true}, {"peak_working_set_bytes", peak_memory()}});
                return 0;
            }
            require(!config.selftest, "selftest-no-generation");
            emit(engine.generate(request, config));
        }
    } catch (const Failure & error) {
        try { emit({{"kind", "error"}, {"id", current_id}, {"error", error.what()}}); } catch (...) {}
    } catch (...) {
        try { emit({{"kind", "error"}, {"id", current_id}, {"error", "internal-failure"}}); } catch (...) {}
    }
    return 2;
}

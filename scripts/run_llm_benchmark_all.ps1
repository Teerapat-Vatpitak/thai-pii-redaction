# Run every hosted model in the LLM-as-detector comparison, one after another.
#
#   .\scripts\run_llm_benchmark_all.ps1
#
# Credentials are read from the User scope rather than the current process, so a
# key set with SetEnvironmentVariable(...,'User') takes effect without opening a
# new terminal. Responses are cached per document, so re-running is free and an
# interrupted run resumes where it stopped.

$ErrorActionPreference = 'Continue'

foreach ($n in 'AIFORTHAI_API_KEY','DOTBLUE_API_KEY','PSU_DOTBLUE_BASE_URL','THAILLM_API_KEY','THAILLM_BASE_URL') {
    $v = [Environment]::GetEnvironmentVariable($n, 'User')
    if ($v) { Set-Item -Path "env:$n" -Value $v }
}
$env:PYTHONUTF8 = '1'

$providers = @(
    'pathumma',
    'dotblue:openai/gpt-4o-mini',
    'dotblue:z-ai/glm-5',
    'dotblue:qwen/qwen3.7-plus',
    'dotblue:PSU-LLM/psu-gemma',
    'thaillm:OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2',
    'thaillm:Typhoon-S-ThaiLLM-8B-Instruct',
    'thaillm:Pathumma-ThaiLLM-qwen3-8b-think-3.0.0'
)

foreach ($p in $providers) {
    $slug = $p -replace '[:/]', '_'
    Write-Host "=== $p ==="
    .\.venv\Scripts\python.exe scripts\run_llm_benchmark.py --provider $p --json "benchmark\reports\llm-$slug-gold.json"
}

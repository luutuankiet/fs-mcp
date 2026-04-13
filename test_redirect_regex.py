import re

def has_file_redirect(command):
    stripped = re.sub(r"'[^']*'", '', command)
    stripped = re.sub(r'"[^"]*"', '', stripped)
    return bool(re.search(r'>{1,2}\s*/(?!dev/)', stripped))

# TRUE POSITIVES (should detect redirect)
assert has_file_redirect('curl http://api > /tmp/data.json'), 'basic redirect'
assert has_file_redirect('ls >> /home/ken/log.txt'), 'append redirect'
assert has_file_redirect('echo test > /tmp/out'), 'echo redirect'
assert has_file_redirect("echo 'x' > /tmp/out"), 'quoted arg then redirect'
assert has_file_redirect('cmd 2>&1 > /tmp/f'), 'fd redirect then file redirect'

# TRUE NEGATIVES (should NOT detect redirect)
assert not has_file_redirect('git status 2>&1'), 'fd redirect only'
assert not has_file_redirect('echo "data > /tmp"'), '> inside double quotes'
assert not has_file_redirect("grep '> /path' file"), '> inside single quotes'
assert not has_file_redirect('echo hello'), 'no redirect'
assert not has_file_redirect('cat file | head'), 'pipe only'
assert not has_file_redirect('cmd > /dev/null'), 'dev null'
assert not has_file_redirect('cmd > /dev/zero'), 'dev zero'
assert not has_file_redirect('cmd 2>&1 > /dev/null'), 'fd redirect then dev null'
assert not has_file_redirect('cmd >/dev/null 2>&1'), 'dev null then fd redirect'
assert not has_file_redirect('docker logs 2>&1 | tail'), 'pipe with fd redirect'
assert not has_file_redirect('echo "> /tmp/fake"'), '> in double quotes path'

# EDGE CASES
assert has_file_redirect('curl -s http://x > /tmp/raw.json && echo done'), 'redirect in compound'
assert not has_file_redirect("awk '{print > \"/file\"}'"), 'awk redirect in quotes'

# DAEMON MODE — curl REST calls (no redirect, RTK SHOULD apply)
assert not has_file_redirect('curl -s localhost:3456/retrieve_tools -d \'{"query":"test"}\''), 'daemon retrieve_tools'
assert not has_file_redirect('curl -s localhost:3456/call_tool -d \'{"name":"server:tool"}\''), 'daemon call_tool'
assert not has_file_redirect('curl -s -X POST http://localhost:3456/describe_tools -d \'{"names":["tool"]}\''), 'daemon describe_tools'
assert not has_file_redirect('curl -s http://localhost:9999/api/v1/servers'), 'proxy admin API'
assert not has_file_redirect('curl -s -H "X-API-Key: admin" http://localhost:8888/api/v1/servers'), 'thinkpad proxy admin'

# DAEMON MODE — escape hatch (HAS redirect, RTK should SKIP)
assert has_file_redirect('curl -s localhost:3456/call_tool -d \'{"name":"tool"}\' > /tmp/raw.json'), 'daemon escape hatch'
assert has_file_redirect('curl -s http://localhost:9999/api/v1/servers > /tmp/proxy.json'), 'proxy admin escape hatch'

# COMPOUND COMMANDS — long chains agents actually write
assert has_file_redirect('curl -s http://api > /tmp/raw.json && echo done'), 'redirect then &&'
assert has_file_redirect('echo start && curl http://api > /tmp/out.json'), 'chain then redirect'
assert has_file_redirect('cd /tmp && curl -s http://api > /tmp/data.json && cat /tmp/data.json | jq .'), 'mid-chain redirect'
assert has_file_redirect('mkdir -p /tmp/out && curl http://api > /tmp/out/result.json 2>&1'), 'redirect + fd redirect'
assert has_file_redirect('curl -H "Authorization: Bearer tok" http://api > /tmp/resp.json; echo $?'), 'semicolon chain'
assert has_file_redirect('SID=$(curl -s -D /tmp/headers http://api) && grep session /tmp/headers > /tmp/sid.txt'), 'subshell + redirect'

# COMPOUND COMMANDS — no file redirect (RTK should apply)
assert not has_file_redirect('git status && git diff'), 'simple chain'
assert not has_file_redirect('docker ps && docker logs container 2>&1 | tail -20'), 'chain + pipe + fd'
assert not has_file_redirect('cd /home/ken && ls -la && echo done'), 'cd chain'
assert not has_file_redirect('npm test 2>&1 || echo failed'), 'or chain with fd'
assert not has_file_redirect('curl -s http://api | jq . | head -5'), 'pipe chain no redirect'
assert not has_file_redirect('for f in *.log; do echo "$f"; done'), 'loop no redirect'
assert not has_file_redirect('ssh root@192.168.1.9 "ls /mnt/us/koreader/plugins/"'), 'ssh quoted command'
assert not has_file_redirect('docker exec kindle-gateway node -e \'console.log("hello")\''), 'docker exec'

# TRICKY PATTERNS
assert not has_file_redirect('echo "curl > /tmp/file" | grep curl'), 'redirect string in pipe'
assert not has_file_redirect("jq '.data > /threshold' file.json"), '> in jq filter'
assert has_file_redirect('cat /proc/cpuinfo > /tmp/cpu.txt'), 'proc redirect'
assert not has_file_redirect('test $count -gt 5 && echo big'), '-gt not a redirect'
assert has_file_redirect('tee /tmp/a.log > /tmp/b.log'), 'tee with redirect'
assert not has_file_redirect('curl http://api 2>&1 | tee /tmp/log.txt'), 'tee via pipe (no >)'

print('ALL 46 TESTS PASSED')

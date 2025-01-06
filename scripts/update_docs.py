#!/usr/bin/env python3

import subprocess
import re

def get_test_output():
    cmd = [
        "docker-compose",
        "-f", "docker-compose.test.yml",
        "run",
        "--rm",
        "-T",
        "test",
        "poetry", "run", "pytest", "-v", "--cov=app", "--cov-report=term-missing"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    filtered_output = []
    for line in result.stdout.split('\n'):
        if line.strip() and not line.startswith('WARN') and not 'Pulling' in line:
            filtered_output.append(line)
    
    return '\n'.join(filtered_output)

def update_readme():
    with open('README.md', 'r') as f:
        content = f.read()
    
    test_output = get_test_output()
    
    test_section = f'''#### Exemples de sortie

1. **Mode test-only (sortie épurée)**
```
{test_output}
```'''
    
    pattern = r'#### Exemples de sortie.*?```\n.*?```'
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, test_section, content, flags=re.DOTALL)
    else:
        content = content.replace('#### Tests dans Docker', f'#### Tests dans Docker\n\n{test_section}')
    
    with open('README.md', 'w') as f:
        f.write(content)

if __name__ == '__main__':
    update_readme() 
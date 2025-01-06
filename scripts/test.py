#!/usr/bin/env python3
"""
Scripts de test pour le système de file d'attente.

Ce module fournit des commandes pour :
- Exécuter les tests
- Générer les rapports de couverture
- Lancer les tests dans Docker
"""

import subprocess
import click
from pathlib import Path
import re

@click.group()
def cli():
    """Commandes de test pour le système de file d'attente."""
    pass

@cli.command()
@click.option('--cov/--no-cov', default=True, help='Active/désactive la couverture de code')
@click.option('--html', is_flag=True, help='Génère un rapport HTML de couverture')
@click.option('--logs', is_flag=True, help='Affiche les logs détaillés des tests')
@click.argument('test_path', required=False)
def run(cov: bool, html: bool, logs: bool, test_path: str):
    """
    Exécute les tests.
    
    Args:
        cov: Active la couverture de code
        html: Génère un rapport HTML
        logs: Affiche les logs détaillés des tests
        test_path: Chemin spécifique des tests à exécuter
    """
    cmd = ["pytest", "-v"]
    
    
    if logs:
        cmd.append("-s")
    
    if cov:
        cmd.extend(["--cov=app", "--cov-report=term-missing"])
    if html:
        cmd.extend(["--cov-report=html"])
    if test_path:
        cmd.append(test_path)
    
    subprocess.run(cmd)

def update_readme_with_output(output: str):
    try:
        with open('README.md', 'r') as f:
            content = f.read()
        
        test_section = f'''#### TEST RESULT

1. **Mode test-only **
```
{output}
```'''
        
        pattern = r'#### TEST RESULT.*?```\n.*?```'
        if re.search(pattern, content, re.DOTALL):
            content = re.sub(pattern, test_section, content, flags=re.DOTALL)
        else:
            content = content.replace('#### TEST RESULT', f'#### TEST RESULT\n\n{test_section}')
        
        with open('README.md', 'w') as f:
            f.write(content)
            
    except Exception as e:
        print(f"Erreur lors de la mise à jour du README: {e}")

@cli.command()
@click.option('--logs', is_flag=True, help='Affiche les logs détaillés des tests')
@click.option('--test-only', is_flag=True, help='Affiche uniquement les logs des tests (pas de build/services)')
@click.option('--update-docs', is_flag=True, help='Met à jour le README avec la sortie des tests')
def docker(logs: bool, test_only: bool, update_docs: bool):
    if test_only:
        cmd = [
            "docker-compose",
            "-f", "docker-compose.test.yml",
            "run",
            "--rm",
            "-T",
            "test",
            "poetry", "run", "pytest", "-v"
        ]
        if logs:
            cmd.append("-s")
        cmd.extend(["--cov=app", "--cov-report=term-missing"])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        filtered_output = []
        for line in result.stdout.split('\n'):
            if line.strip() and not line.startswith('WARN') and not 'Pulling' in line and not 'Pulled' in line:
                filtered_output.append(line)
        
        output = '\n'.join(filtered_output)
        print(output)
        
        if update_docs and result.returncode == 0:
            update_readme_with_output(output)
        
        if result.returncode != 0:
            exit(result.returncode)
    else:
        cmd = [
            "docker-compose",
            "-f", "docker-compose.test.yml",
            "up",
            "--build",
        ]
        
        if logs:
            subprocess.run([
                "docker-compose",
                "-f", "docker-compose.test.yml",
                "build",
                "--no-cache",
                "test"
            ])
            result = subprocess.run([
                "docker-compose",
                "-f", "docker-compose.test.yml",
                "run",
                "--rm",
                "test",
                "poetry", "run", "pytest", "-v", "-s", "--cov=app", "--cov-report=term-missing"
            ], capture_output=True, text=True)
            
            if update_docs and result.returncode == 0:
                update_readme_with_output(result.stdout)
        else:
            cmd.append("--abort-on-container-exit")
            subprocess.run(cmd)

def run_tests_in_docker():
    """Lance les tests dans l'environnement Docker."""
    cmd = "docker-compose -f docker-compose.test.yml up --build --force-recreate test"
    result = subprocess.run(cmd.split(), capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode

def run_tests(args):
    """Lance les tests avec les options spécifiées."""
    cmd = ["pytest", "-v", "-s"]
    
    if args.cov:
        cmd.extend(["--cov=app", "--cov-report=term-missing"])
    
    if args.html:
        cmd.extend(["--cov-report=html"])
    
    if args.test_path:
        cmd.append(args.test_path)
    
    result = subprocess.run(cmd)
    return result.returncode

if __name__ == '__main__':
    cli() 
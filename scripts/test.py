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

@click.group()
def cli():
    """Commandes de test pour le système de file d'attente."""
    pass

@cli.command()
@click.option('--cov/--no-cov', default=True, help='Active/désactive la couverture de code')
@click.option('--html', is_flag=True, help='Génère un rapport HTML de couverture')
@click.argument('test_path', required=False)
def run(cov: bool, html: bool, test_path: str):
    """
    Exécute les tests.
    
    Args:
        cov: Active la couverture de code
        html: Génère un rapport HTML
        test_path: Chemin spécifique des tests à exécuter
    """
    cmd = ["pytest"]
    if cov:
        cmd.extend(["--cov=app"])
        if html:
            cmd.extend(["--cov-report=html"])
    if test_path:
        cmd.append(test_path)
    
    subprocess.run(cmd)

@cli.command()
def docker():
    """Lance les tests dans un conteneur Docker."""
    subprocess.run([
        "docker-compose",
        "-f", "docker-compose.test.yml",
        "up",
        "--build",
        "--abort-on-container-exit"
    ])

if __name__ == '__main__':
    cli() 
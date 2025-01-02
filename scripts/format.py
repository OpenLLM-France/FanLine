#!/usr/bin/env python3
"""
Scripts de formatage pour le système de file d'attente.

Ce module fournit des commandes pour :
- Formater le code avec black
- Trier les imports avec isort
- Vérifier le style avec flake8
"""

import subprocess
import click
from pathlib import Path

@click.group()
def cli():
    """Commandes de formatage pour le système de file d'attente."""
    pass

@cli.command()
@click.option('--check', is_flag=True, help='Vérifie le formatage sans modifier les fichiers')
def black(check: bool):
    """Formate le code avec black."""
    cmd = ["black", "."]
    if check:
        cmd.append("--check")
    subprocess.run(cmd)

@cli.command()
def isort():
    """Trie les imports avec isort."""
    subprocess.run(["isort", "."])

@cli.command()
def lint():
    """Vérifie le style avec flake8."""
    subprocess.run(["flake8"])

@cli.command()
def all():
    """Exécute tous les formatages (black, isort, flake8)."""
    subprocess.run(["black", "."])
    subprocess.run(["isort", "."])
    subprocess.run(["flake8"])

if __name__ == '__main__':
    cli() 
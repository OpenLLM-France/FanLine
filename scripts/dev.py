#!/usr/bin/env python3
"""
Scripts de développement pour le système de file d'attente.

Ce module fournit des commandes pour :
- Lancer l'application en mode développement
- Gérer les conteneurs Docker
- Exécuter les tests
- Formater le code
"""

import subprocess
import click
import os
from typing import Optional

@click.group()
def cli():
    """Outils de développement pour le système de file d'attente."""
    pass

@cli.command()
@click.option('--host', default='0.0.0.0', help='Hôte de l\'application')
@click.option('--port', default=8000, help='Port de l\'application')
@click.option('--reload', is_flag=True, help='Active le rechargement automatique')
def run(host: str, port: int, reload: bool):
    """Lance l'application FastAPI en mode développement."""
    reload_flag = "--reload" if reload else ""
    cmd = f"uvicorn app.main:app --host {host} --port {port} {reload_flag}"
    subprocess.run(cmd.split())

@cli.command()
def docker_up():
    """Lance tous les services avec Docker Compose."""
    subprocess.run(["docker-compose", "up", "--build", "-d"])
    click.echo("Services démarrés en arrière-plan")

@cli.command()
def docker_down():
    """Arrête tous les services Docker."""
    subprocess.run(["docker-compose", "down"])
    click.echo("Services arrêtés")

@cli.command()
def docker_logs():
    """Affiche les logs des services Docker."""
    subprocess.run(["docker-compose", "logs", "-f"])

if __name__ == '__main__':
    cli() 
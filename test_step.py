#!/usr/bin/env python
"""Test script to run multiple steps until completion."""
import sys
import uuid

sys.path.insert(0, "/Users/hidekinishida/Documents/Projetos/Agente de IA Local/src")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from agent.config import get_settings
from agent.persistence.models import Base, ExecutionRunModel, TaskModel
from agent.domain.enums import TaskStatus
from agent.orchestrator.runner import RunOrchestrator

settings = get_settings()
engine = create_engine(settings.resolved_database_url(), connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

session = Session()

run_id = uuid.UUID("71484d7b-e9c2-46ac-89f5-d07509a3fddf")
run = session.get(ExecutionRunModel, run_id)
if run is None:
    print(f"Run {run_id} not found")
    sys.exit(1)

print(f"Run found: {run.id}, status: {run.status}, root_task_id: {run.root_task_id}")

orch = RunOrchestrator(session, settings)

import asyncio

for i in range(20):
    # Check root task status
    root = session.get(TaskModel, run.root_task_id)
    print(f"\n=== Step {i+1} ===")
    print(f"Root status: {root.status}, consolidated_result_json: {root.consolidated_result_json is not None}")
    
    try:
        result = asyncio.run(orch.step(run.id))
        print(f"Action: {result.get('action')}")
        
        # Check task statuses
        tasks = session.query(TaskModel).filter(TaskModel.project_id == run.project_id).all()
        for t in tasks:
            if t.parent_id == run.root_task_id or t.id == run.root_task_id:
                print(f"  Task {str(t.id)[:8]}: {t.status} - {t.title[:50]}")
        
        if result.get("action") in ("run_completed", "run_terminal"):
            print("Run completed!")
            break
        if result.get("action") == "waiting":
            print("Waiting...")
            break
    except Exception as e:
        import traceback
        print(f"Error on step {i+1}: {e}")
        traceback.print_exc()
        break

session.close()
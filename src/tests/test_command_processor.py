import pytest
from core.command_processor import CommandProcessor


class FakeAI:
    def route_command(self, text):
        return {"intent": None, "respuesta": text}


class FakeAction:
    def __init__(self, result="", should_raise=False):
        self.result = result
        self.should_raise = should_raise
        self.calls = []

    def execute(self, intent_data):
        self.calls.append(intent_data)
        if self.should_raise:
            raise RuntimeError("boom")
        return self.result


class FakePlanner:
    def __init__(self, steps):
        self.steps = steps
        self.commands = []

    def create_plan(self, command):
        self.commands.append(command)
        return self.steps


class FakeExecutor:
    def __init__(self, result):
        self.result = result
        self.steps = []

    def execute_plan(self, steps):
        self.steps.append(steps)
        return self.result


def build_processor(action=None, planner=None, executor=None):
    return CommandProcessor(
        ai_service=FakeAI(),
        action_service=action or FakeAction(),
        planner=planner,
        executor=executor,
    )


def test_execute_returns_spoken_response_when_no_intent():
    processor = build_processor()

    response = processor._execute({"intent": None, "respuesta": "Hola."})

    assert response == "Hola."


def test_execute_uses_action_result_for_direct_response_intents():
    action = FakeAction("Son las 10:00 AM.")
    processor = build_processor(action=action)

    response = processor._execute({"intent": "dar_hora_fecha", "respuesta": "Claro."})

    assert response == "Son las 10:00 AM."


@pytest.mark.parametrize(
    "unknown_action_result",
    ["Accion desconocida: saludar", "Acci\u00f3n desconocida: saludar"],
)
def test_execute_ignores_unknown_action_and_keeps_ai_response(unknown_action_result):
    action = FakeAction(unknown_action_result)
    processor = build_processor(action=action)

    response = processor._execute({"intent": "saludar", "respuesta": "Hola, Jesus."})

    assert response == "Hola, Jesus."


def test_execute_plan_task_uses_planner_and_executor():
    steps = [{"intent": "abrir_aplicacion", "target": "notepad"}]
    planner = FakePlanner(steps)
    executor = FakeExecutor("Plan ejecutado.")
    action = FakeAction("no debe ejecutarse")
    processor = build_processor(action=action, planner=planner, executor=executor)

    response = processor._execute(
        {"intent": "plan_task", "respuesta": "Voy."},
        command_text="abre notepad",
    )

    assert response == "Plan ejecutado."
    assert planner.commands == ["abre notepad"]
    assert executor.steps == [steps]
    assert action.calls == []


def test_execute_plan_task_returns_clear_message_when_plan_is_empty():
    processor = build_processor(
        planner=FakePlanner([]),
        executor=FakeExecutor("no debe ejecutarse"),
    )

    response = processor._execute({"intent": "plan_task"}, command_text="haz varias cosas")

    assert response == "No pude generar un plan valido para esa tarea."


def test_execute_returns_fallback_when_action_raises():
    processor = build_processor(action=FakeAction(should_raise=True))

    response = processor._execute({"intent": "abrir_aplicacion", "respuesta": "Voy."})

    assert response == "No pude completar la accion solicitada."


@pytest.mark.parametrize("invalid_intent_data", [None, [], "texto"])
def test_execute_handles_invalid_intent_data(invalid_intent_data):
    processor = build_processor()

    response = processor._execute(invalid_intent_data)

    assert response == "Entendido."

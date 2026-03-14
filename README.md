El objetivo es que tengas un agente con:

ReAct loop

tools reales

memoria simple

RAG opcional

estructura extensible

Todo en un único script para empezar.

> [!NOTE]
> **AI AGENTS**: This project has evolved past the single-script approach described below. Please read `CONTEXT.md` for the current, advanced Multi-Container architecture based on Model Context Protocol (MCP).

1. Estructura mínima del proyecto

Crea esta carpeta:

react-agent/
│
├─ agent.py
├─ tools.py
├─ memory.json
└─ docs/


2. Script principal (agent.py)

Este agente implementa:

ReAct loop

llamadas a tools

conexión a LM Studio

"
import requests
import json
import re
from tools import TOOLS

LLM_ENDPOINT = "http://100.116.250.89:1234/v1/chat/completions"
MODEL_NAME = "gpt-oss-20b"

MAX_STEPS = 6


def call_llm(messages):

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.2
    }

    r = requests.post(LLM_ENDPOINT, json=payload)
    return r.json()["choices"][0]["message"]["content"]


def load_memory():

    try:
        with open("memory.json") as f:
            return json.load(f)
    except:
        return {}


def save_memory(memory):

    with open("memory.json","w") as f:
        json.dump(memory,f,indent=2)


def build_tools_prompt():

    text = ""

    for name, tool in TOOLS.items():

        text += f"{name}: {tool['description']}\n"

    return text


def parse_action(text):

    action_match = re.search(r"Action:\s*(\w+)", text)
    input_match = re.search(r"Action Input:\s*(.*)", text)

    if not action_match:
        return None

    action = action_match.group(1)

    params = {}

    if input_match:

        try:
            params = json.loads(input_match.group(1))
        except:
            pass

    return action, params


def run_tool(action, params):

    if action not in TOOLS:
        return "Tool not found"

    try:
        result = TOOLS[action]["function"](**params)
        return str(result)
    except Exception as e:
        return str(e)


def react_agent(user_input):

    memory = load_memory()

    system_prompt = f"""
You are an AI agent using the ReAct framework.

You can think, act and observe.

Format:

Thought: reasoning
Action: tool_name
Action Input: JSON
Observation: tool result

When finished respond:

Final Answer: result

Available tools:

{build_tools_prompt()}

User preferences memory:
{json.dumps(memory)}
"""

    messages = [
        {"role":"system","content":system_prompt},
        {"role":"user","content":user_input}
    ]

    scratchpad = ""

    for step in range(MAX_STEPS):

        response = call_llm(messages)

        print("\nLLM:",response)

        if "Final Answer:" in response:
            return response.split("Final Answer:")[-1].strip()

        parsed = parse_action(response)

        if not parsed:
            return response

        action, params = parsed

        observation = run_tool(action, params)

        scratchpad += f"\n{response}\nObservation: {observation}\n"

        messages.append({"role":"assistant","content":response})
        messages.append({"role":"user","content":f"Observation: {observation}"})


    return "Max steps reached"


def main():

    print("ReAct Agent ready\n")

    while True:

        user = input(">> ")

        if user == "exit":
            break

        result = react_agent(user)

        print("\nAgent:", result)


if __name__ == "__main__":
    main()
"


3. Tools (tools.py)

Ejemplo de tools iniciales.

"
import os
import requests

def get_time():

    from datetime import datetime
    return str(datetime.now())


def read_file(path):

    with open(path) as f:
        return f.read()[:2000]


def list_files(path="."):

    return os.listdir(path)


def http_get(url):

    r = requests.get(url)
    return r.text[:2000]


TOOLS = {

    "get_time": {
        "description": "get current system time",
        "function": get_time
    },

    "read_file": {
        "description": "read a file from disk. input: {\"path\":\"file\"}",
        "function": read_file
    },

    "list_files": {
        "description": "list files in directory. input: {\"path\":\"dir\"}",
        "function": list_files
    },

    "http_get": {
        "description": "fetch a web url. input: {\"url\":\"http://...\"}",
        "function": http_get
    }

}
"

4. memory.json

Inicialmente vacío:

"{}"

Luego puedes guardar cosas como:

"
{
 "home_api": "http://192.168.1.20"
}
"

5. Ejecutar el agente
"
pip install requests
python agent.py
"

Ejemplo:

">> que hora es"


Flujo típico:

"
Thought: necesito saber la hora
Action: get_time
Action Input: {}

Observation: 2026-03-14 21:03
Final Answer: Son las 21:03
"

6. Integrar tus APIs domóticas

Añade tool:

"
def open_blinds(room):

    url = f"http://192.168.1.50/api/blinds/open?room={room}"
    r = requests.get(url)

    return r.text
"

Registro:


"open_blinds":{
 "description":"open blinds in room {room}",
 "function":open_blinds
}
"


7. Integración MCP (opcional)

Si ya tienes servidores Model Context Protocol, puedes crear una tool genérica:

"
def mcp_call(tool, params):

    r = requests.post(
        "http://localhost:8000/mcp",
        json={"tool":tool,"params":params}
    )

    return r.json()
"


8. Añadir RAG rápido

Instala:

"
pip install sentence-transformers qdrant-client
"

Usa vector DB:

Qdrant

Tool:

def search_docs(query):
9. Mejoras recomendadas

Luego puedes añadir:

planner

separar planificación del executor.

tool schemas

usar JSON schema.

streaming

para respuestas más rápidas.

sandbox

ejecutar tools en docker.

10. Experimentos interesantes que puedes probar

Con este agente puedes experimentar con:

control de tu red doméstica

análisis de logs

domótica

scraping

agentes autónomos
# External Research & Documentation Policy

## Purpose

You have access to an MCP research server backed by SERP API.

Use it as an external knowledge layer when the task requires information that is not reliably available in the current project context.

The goal is NOT to search the internet for every task.

The goal is to retrieve the minimum amount of authoritative, current information required to make a technically correct decision.

---

## Core Rule

Before implementing a task, determine whether the available context is sufficient.

Use MCP research when:

- you are unsure about an API, command, configuration option, protocol, or behavior;
- the task depends on current software versions;
- documentation may have changed since your training data;
- you encounter an unfamiliar error;
- you need exact syntax for a CLI, SDK, API, Docker image, configuration file, or infrastructure component;
- the user explicitly asks for current information;
- implementation depends on external service behavior;
- there are multiple possible implementations and current documentation can resolve the choice.

Do NOT guess technical details that can be verified through MCP research.

---

## Research Priority

When researching technical information, prefer sources in this order:

1. Official documentation
2. Official GitHub repository
3. Official API reference
4. Official release notes / changelog
5. Maintainer documentation
6. High-quality technical sources
7. Community discussions only when official documentation does not answer the question

For security, networking, authentication, infrastructure, deployment, or production configuration, strongly prefer primary sources.

---

## Research Workflow

When additional information is required:

### 1. Identify the knowledge gap

Do not search broadly.

Determine exactly what information is missing.

Example:

BAD:

"How to configure nginx"

GOOD:

"nginx 1.28 stream module TCP proxy configuration official documentation"

---

### 2. Search through MCP

Use the available SERP/research MCP tools.

Search specifically for the missing information.

Prefer queries containing:

- technology name;
- current version when known;
- exact feature;
- exact error message when debugging;
- "official documentation";
- current year only when freshness matters.

---

### 3. Retrieve only relevant information

Do not ingest entire websites or large documentation trees unless necessary.

Retrieve the smallest relevant documentation sections.

Avoid filling the context window with unrelated information.

---

### 4. Verify important decisions

For infrastructure, networking, security, authentication, databases, deployment, and destructive operations:

verify critical configuration against authoritative documentation before executing or recommending it.

If sources disagree, prefer official documentation and explicitly note the uncertainty.

---

### 5. Build a working context

Convert research results into concise working knowledge.

Keep:

- required commands;
- configuration syntax;
- version constraints;
- important warnings;
- compatibility information;
- relevant examples.

Discard unrelated text.

Do not copy large documentation pages into the working context.

---

### 6. Continue the task

After research, return to the original task.

Research is a supporting operation, not the final goal.

Do not stop after finding documentation if the task requires implementation.

---

## Project Context First

Before external research, inspect the minimum necessary project context.

Do NOT scan the entire repository automatically.

Start with:

- relevant files;
- configuration;
- dependency manifests;
- existing architecture;
- files directly related to the requested task.

Expand repository inspection only when required.

External research does not replace understanding the existing project.

---

## Token Efficiency

Protect the context window.

Never:

- crawl documentation without a reason;
- load entire websites;
- read the entire repository by default;
- perform repeated searches for information already obtained;
- paste large search results into context.

Use this loop:

TASK
→ inspect relevant project context
→ identify missing knowledge
→ MCP research
→ extract relevant facts
→ implement
→ verify

---

## Freshness Rule

Never rely only on model memory for information that is likely to change.

Examples:

- API endpoints;
- model availability;
- package versions;
- CLI commands;
- cloud provider behavior;
- pricing;
- SDK interfaces;
- authentication methods;
- Docker images;
- deployment procedures;
- service limitations.

Research these when they materially affect the task.

---

## Error Handling

When a command or implementation fails:

1. Read the actual error.
2. Inspect relevant local configuration.
3. Form a hypothesis.
4. If the cause is uncertain, research the exact error through MCP.
5. Prefer official documentation and issue trackers.
6. Apply the smallest reasonable fix.
7. Verify the result.

Do not repeatedly modify configuration without understanding the failure.

---

## Infrastructure Safety

Before changing:

- firewall rules;
- SSH;
- routing;
- reverse proxies;
- DNS;
- Docker networking;
- VPNs;
- system services;
- authentication;
- production databases;

first understand the existing state.

Prefer reversible changes.

Before destructive or connectivity-sensitive operations, explain the impact and ensure a rollback path exists.

Never expose secrets, API keys, passwords, private keys, or credentials in research queries.

---

## Research Decision Example

Task:

Configure a multi-server reverse-proxy architecture.

Reasoning process:

1. Inspect the current server/network configuration.
2. Determine which technologies and versions are involved.
3. Identify uncertain configuration details.
4. Research those specific details through MCP.
5. Prefer official documentation.
6. Extract only required configuration knowledge.
7. Design the architecture.
8. Implement incrementally.
9. Test connectivity at every hop.
10. Verify the final route.

Do not search for a complete solution and blindly copy it.

---

## Fundamental Principle

Use your reasoning for architecture and decisions.

Use project context for understanding the existing system.

Use MCP research for external facts and current documentation.

Use tools for execution and verification.

When uncertain:

DO NOT GUESS → RESEARCH → VERIFY → CONTINUE.
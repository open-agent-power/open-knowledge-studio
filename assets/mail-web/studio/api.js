// Instance-bound transport. Capability checks remain enforced by the server.
export function createStudioApi(workspace, getContext) {
  return {
    request: workspace.request,
    async post(route, payload) {
      const context = getContext();
      if (context?.local_edit !== true) throw Error("当前为只读模式");
      return workspace.request(route, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...payload,
          expected_knowledge_base: context.knowledge_base,
        }),
      });
    },
  };
}

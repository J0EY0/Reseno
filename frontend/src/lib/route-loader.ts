export function createRouteLoader<Module, Key extends keyof Module>(
  loader: () => Promise<Module>,
  component: Key,
) {
  let request: Promise<{ default: Module[Key] }>;
  return () =>
    (request ||= loader().then((module) => ({ default: module[component] })));
}

<script>
    import AdminSidebar from "$lib/admin_cmpnts/AdminSidebar.svelte";
    import { Card, Toggle, Button, Range, Label, Input } from "flowbite-svelte";

    // Keep in mind these values are the MAXIMUM values for the range selectors, not the current values
    const max_nb_connections_range = 1000;
    const draft_time_limit_range = 60; // In minutes

    let config = {
        max_nb_connections: 50,
        draft_time_limit: 5,
    };
</script>

<div class="min-h-screen dark:bg-gray-900">
    <div class="flex">
        <AdminSidebar />
        <div class="p-4 w-full gap-4 h-screen overflow-y-auto">
            <div>
                <h5
                    class="mb-2 text-2xl font-bold tracking-tight text-gray-900 dark:text-white"
                >
                    Configuration settings
                </h5>
                <Card class="w-full max-w-none mb-4">
                    <div>
                        <Label>Maximum simultaneous users</Label>
                        <div class="flex items-center gap-4">
                            <Range
                                min="0"
                                max={max_nb_connections_range}
                                bind:value={config.max_nb_connections}
                            />
                            <Input
                                type="number"
                                bind:value={config.max_nb_connections}
                                class="w-16"
                            />
                        </div>
                    </div>
                    <div>
                        <Label>Time limit in draft queue (in minutes)</Label>
                        <div class="flex items-center gap-4">
                            <Range
                                min="0"
                                max={draft_time_limit_range}
                                bind:value={config.draft_time_limit}
                            />
                            <Input
                                type="number"
                                bind:value={config.draft_time_limit}
                                class="w-16"
                            />
                        </div>
                    </div>
                </Card>
            </div>

            <div>
                <h5
                    class="mb-2 text-2xl font-bold tracking-tight text-gray-900 dark:text-white"
                >
                    Panic settings
                </h5>
                <Card class="w-full max-w-none gap-4">
                    <Toggle>Enable new connections to Lucie Chat</Toggle>
                    <Button>Kick all users</Button>
                </Card>
            </div>
        </div>
    </div>
</div>

<style>
    /* Les styles sont gérés par Tailwind CSS */
</style>

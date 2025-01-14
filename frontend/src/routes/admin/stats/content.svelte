<script lang="ts">
    import AdminChart from "$lib/admin_cmpnts/AdminChart.svelte";
    import AdminTable from "$lib/admin_cmpnts/AdminTable.svelte";
    import { Card } from "flowbite-svelte";
    import { onMount } from "svelte";
    import { getStatus } from "$lib/queue";
    import { getUsers } from "$lib/queue";
    import type { QueueStatus } from "$lib/types";

    let test_data = {
            name: "test",
            data: [1, 5, 3, 10],
            color: "#1C64F2",
        };

    let columns = [
        {
            label: "ID",
            key: "user_id",
        },
        {
            label: "Status",
            key: "status",
        },
        {
            label: "Position",
            key: "position",
        }
    ];
    let users: {
        active_users: QueueStatus[],
        draft_users: QueueStatus[],
        waiting_users: QueueStatus[]
    } = {
        active_users: [],
        draft_users: [],
        waiting_users: []
    };

    async function fetchCurQueueStatus() {
        try {
            const data = await getUsers();

            users.active_users = await Promise.all(
                data.active_users.map(async (user_id: string) => await getStatus(user_id))
            );

            users.draft_users = await Promise.all(
                data.draft_users.map(async (user_id: string) => await getStatus(user_id))
            );

            users.waiting_users = await Promise.all(
                data.waiting_users.map(async (user_id: string) => await getStatus(user_id))
            );

        } catch (error) {
            console.error("Error fetching queue status:", error);
        }
    }

    setInterval(() => {
        fetchCurQueueStatus();
    }, 5000);
</script>

<div class="w-full p-4 h-screen overflow-y-auto">
    <div
        class="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4 mb-4"
    >
        <AdminChart
            main_value="2"
            unit="test"
            chart_data={test_data}
            height="200px"
            show_graph={true}
        />
        <AdminChart
            main_value="2"
            unit="test"
            chart_data={test_data}
            height="200px"
            show_graph={true}
        />
    </div>
    <AdminTable {columns} data={users.active_users} />
    <AdminTable {columns} data={users.draft_users} />
    <AdminTable {columns} data={users.waiting_users} />

</div>
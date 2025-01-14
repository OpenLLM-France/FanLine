<script>
    import AdminChart from "$lib/admin_cmpnts/AdminChart.svelte";
    import AdminTable from "$lib/admin_cmpnts/AdminTable.svelte";
    import { Card } from "flowbite-svelte";
    import { onMount } from "svelte";

    let test_data = {
            name: "test",
            data: [1, 5, 3, 10],
            color: "#1C64F2",
        };

    let columns = [
        "ID",
        "Status",
        "Position",
        "Time since join",
        "Draft timer",
        "Session timer",
    ];
    let users = {
        active_users: [],
        draft_users: [],
        waiting_users: [],
    };

    // TODO resolve fetch through queue.ts (api interface)
    function fetchCurQueueStatus() {
        fetch("http://localhost:8000/queue/get_users")
            .then((res) => res.json())
            .then((data) => {
                console.log(data);
                users = data;
            });
    }

    setInterval(() => {
        fetchCurQueueStatus();
    }, 1000);
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
<script lang="ts">
    
    import SvelteTable from 'svelte-table';
    import { Heart, Trash, Check } from 'svelte-iconoir';

    import { joinQueue, getMetrics, leaveQueue, confirmConnection } from './queue';
    import type { UserRequest } from './types';

    let users = [];

    const columns = [
        { title: 'ID', key: 'id', value: v => v.id },
        { title: 'Status', key: 'status', value: v => v.status },
        { title: 'Position', key: 'position', value: v => v.position },
        { title: 'Time since join', key: 'timeSinceJoin', value: v => v.timeSinceJoin },
        { title: 'Draft timer', key: 'draftTimer', value: v => v.draftTimer },
        { title: 'Session timer', key: 'sessionTimer', value: v => v.sessionTimer },
        { title: 'Heartbeat', key: 'heartbeat', renderComponent: Heart},
        { title: 'Leave', key: 'leave', renderComponent: Trash},
        { title: 'Confirm', key: 'confirm', renderComponent: Check}
    ];

    let queueStatus = 'unknown';
    let queueLength = 0;
    let testingLength = 0;

    let lastResponse = '';

    function generateRandomUser() {
        let user: UserRequest = {
            user_id: Math.random().toString(36).substring(2, 9)
        };

        // Temporary solution to test table. This functionnality is supposed to be handled through an endpoint.
        let new_user = {
            id: user.user_id,
            status: 'waiting',
            position: users.length + 1,
            timeSinceJoin: 0,
            draftTimer: 0,
            sessionTimer: 0,
            heartbeat: 'heartbeat',
            leave: 'leave'
        }

        users = [...users, new_user];
        console.log(users)
        return user;
    }

    function handleAddUserToQueue() {
        let user = generateRandomUser();
        console.log('Adding user to queue');
        joinQueue(user).then(data => {
            console.log(data);
            lastResponse = JSON.stringify(data);
        }).catch(err => {
            console.error(err.message);
            lastResponse = JSON.stringify(err.message);
        });
    }

    function handleGetMetrics() {
        console.log('Getting metrics');
        getMetrics().then(data => {
            console.log(data);
            lastResponse = JSON.stringify(data);
        }).catch(err => {
            console.error(err.message);
            lastResponse = JSON.stringify(err.message);
        });
    }


    function handleClick(e) {
        let detail = e.detail;

        if (detail.key == 'heartbeat') {
            handleHeartbeat(detail.row);
        } else if (detail.key == 'leave') {
            handleLeaveQueue(detail.row);
        } else if (detail.key == 'confirm') {
            handleConfirmConnection(detail.row);
        }
        console.log(e)
    }

    function handleHeartbeat(row) {
        console.log('Heartbeat for user', row.id);
    }

    function handleLeaveQueue(row) {
        console.log('Leaving queue for user', row.id);
        leaveQueue(row.id).then(data => {
            console.log(data);
            lastResponse = JSON.stringify(data);
        }).catch(err => {
            console.error(err.message);
            lastResponse = JSON.stringify(err.message);
        });
    }

    function handleConfirmConnection(row) {
        console.log('Confirming user', row.id);
        confirmConnection(row.id).then(data => {
            console.log(data);
            lastResponse = JSON.stringify(data);
        }).catch(err => {
            console.error(err.message);
            lastResponse = JSON.stringify(err.message);
        });
    }

</script>

<div class="absolute top-0 left-0 right-0 flex flex-col items-center bg-gray-100">
    <div class="mt-6 relative bg-white pt-10 pb-2 px-2 shadow-xl ring-1 ring-gray-900/5 sm:mx-auto sm:max-w-lg sm:rounded-lg rounded">
        <h1 class="text-xl font-bold mb-4 mx-6">Response</h1>
        <div class="relative bg-black pt-10 pb-8 px-4 ring-1 text-white ring-gray-900/5 sm:mx-auto sm:max-w-lg sm:rounded-lg rounded font-mono overflow-scroll">
            {lastResponse}
        </div>
    </div>
    <div class="mt-6 relative bg-white px-6 pt-10 pb-8 shadow-xl ring-1 ring-gray-900/5 sm:mx-auto sm:max-w-lg sm:rounded-lg  rounded">
        <h1 class="text-xl font-bold mb-4">Admin</h1>
        <p>Simulate users entering, leaving, and timing out in the queue</p>
        <div class="flex space-x-2 my-4">
            <button class="bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded" on:click={handleAddUserToQueue}>Add to queue</button>
            <button class="bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded" on:click={handleGetMetrics}>Get Metrics</button>
        </div>
        <div>
            <SvelteTable 
                columns="{columns}" 
                rows="{users}" 
                on:clickCell="{handleClick}"    
                class="w-full"
            />
        </div>
    </div>
</div>


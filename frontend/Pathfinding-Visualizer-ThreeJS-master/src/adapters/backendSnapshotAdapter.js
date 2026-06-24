function createNode(row, col, cols, previousNode) {
	const node = previousNode || {};
	node.id = row * cols + col;
	node.row = row;
	node.col = col;
	node.status = node.status || "unknown";
	node.backendState = node.backendState || "UNKNOWN";
	node.distance = Infinity;
	node.totalDistance = Infinity;
	node.heuristicDistance = null;
	node.direction = null;
	node.weight = 0;
	node.previousNode = null;
	return node;
}

function createGrid(width, height, previousGrid = null) {
	if (
		previousGrid &&
		previousGrid.length === height &&
		previousGrid.every((row) => row && row.length === width)
	) {
		return previousGrid;
	}

	const grid = [];
	for (let row = 0; row < height; row++) {
		const currentRow = [];
		for (let col = 0; col < width; col++) {
			const previousNode = previousGrid && previousGrid[row] && previousGrid[row][col];
			currentRow.push(createNode(row, col, width, previousNode));
		}
		grid.push(currentRow);
	}
	return grid;
}

function mapCellStateToNodeStatus(state) {
	if (state === "OBSTACLE") return "wall";
	if (state === "VISITED") return "visited";
	if (state === "FREE") return "default";
	if (state === "RESERVED") return "reserved";
	return "unknown";
}

function applyCellToGrid(grid, cell, changedCells = null) {
	const row = Number(cell.y);
	const col = Number(cell.x);
	if (!grid[row] || !grid[row][col]) return;

	const node = grid[row][col];
	const previousStatus = node.status;
	node.vehicleReserved = false;
	node.reservedByVehicle = null;
	node.backendState = cell.state;
	node.status = mapCellStateToNodeStatus(cell.state);
	node.confidence = cell.confidence;
	node.updatedBy = cell.updatedBy;
	node.updatedAt = cell.updatedAt;
	if (changedCells && previousStatus !== node.status) {
		changedCells.push({ row, col });
	}
}

function clearVehicleReservations(grid, changedCells = null) {
	for (const row of grid) {
		for (const node of row) {
			if (!node.vehicleReserved) continue;
			const previousStatus = node.status;
			node.vehicleReserved = false;
			node.reservedByVehicle = null;
			node.status = mapCellStateToNodeStatus(node.backendState);
			if (changedCells && previousStatus !== node.status) {
				changedCells.push({ row: node.row, col: node.col });
			}
		}
	}
}

function applyVehicleReservations(grid, vehicles, changedCells = null) {
	for (const vehicle of vehicles) {
		const row = Number(vehicle.row);
		const col = Number(vehicle.col);
		if (!grid[row] || !grid[row][col]) continue;

		const node = grid[row][col];
		if (node.backendState === "OBSTACLE") continue;

		const previousStatus = node.status;
		node.vehicleReserved = true;
		node.reservedByVehicle = vehicle.id;
		node.status = "reserved";
		if (changedCells && previousStatus !== node.status) {
			changedCells.push({ row, col });
		}
	}
}

function adaptVehicle(vehicle) {
	const position = vehicle.pose && vehicle.pose.position ? vehicle.pose.position : {};
	return {
		id: vehicle.vehicleId,
		row: Number(position.y || 0),
		col: Number(position.x || 0),
		heading: Number((vehicle.pose && vehicle.pose.heading) || 0),
		status: vehicle.status,
		battery: vehicle.battery,
		currentTaskId: vehicle.currentTaskId,
		currentPlanId: vehicle.currentPlanId,
		currentStepIndex: vehicle.currentStepIndex || 0,
	};
}

function adaptFrontier(frontier) {
	const position = frontier.position || {};
	return {
		id: frontier.frontierId,
		row: Number(position.y || 0),
		col: Number(position.x || 0),
		unknownGain: frontier.unknownGain,
		status: frontier.status,
	};
}

function adaptStep(step, vehicleId, planId) {
	const position = step.position || {};
	return {
		row: Number(position.y || 0),
		col: Number(position.x || 0),
		stepIndex: step.stepIndex,
		expectedTimeSlot: step.expectedTimeSlot,
		heading: step.heading,
		action: step.action,
		vehicleId,
		planId,
	};
}

function isInBounds(item, width, height) {
	return (
		Number.isFinite(item.row) &&
		Number.isFinite(item.col) &&
		item.row >= 0 &&
		item.row < height &&
		item.col >= 0 &&
		item.col < width
	);
}

function remainingPathForTask(task, vehicle) {
	const path = task.pathQueue || [];
	if (!path.length || !vehicle) return [];

	const currentIndex = Math.max(0, Number(task.currentStepIndex || 0));
	const remainingSteps = path.slice(currentIndex + 1).map((step) =>
		adaptStep(step, task.vehicleId, task.planId)
	);
	const currentPosition = {
		row: vehicle.row,
		col: vehicle.col,
		stepIndex: currentIndex,
		vehicleId: task.vehicleId,
		planId: task.planId,
	};

	return [currentPosition, ...remainingSteps].filter((step, index, steps) => {
		if (index === 0) return true;
		const previous = steps[index - 1];
		return step.row !== previous.row || step.col !== previous.col;
	});
}

export function adaptSnapshot(snapshot, previousGrid = null) {
	const map = snapshot.map || { width: 0, height: 0, cells: [] };
	const width = Number(map.width || 0);
	const height = Number(map.height || 0);
	const grid = createGrid(width, height, previousGrid);
	const changedCells = [];

	for (const cell of map.cells || []) {
		applyCellToGrid(grid, cell, changedCells);
	}

	for (const cell of (snapshot.mapDelta && snapshot.mapDelta.cells) || []) {
		applyCellToGrid(grid, cell, changedCells);
	}

	const vehicles = (snapshot.vehicles || [])
		.map(adaptVehicle)
		.filter((vehicle) => isInBounds(vehicle, width, height));
	const vehiclesById = Object.fromEntries(vehicles.map((vehicle) => [vehicle.id, vehicle]));
	clearVehicleReservations(grid, changedCells);
	applyVehicleReservations(grid, vehicles, changedCells);

	const frontiers = (snapshot.frontiers || [])
		.map(adaptFrontier)
		.filter((frontier) => isInBounds(frontier, width, height))
		.filter((frontier) => ["OPEN", "ASSIGNED"].includes(frontier.status));

	const pathsByVehicle = {};
	for (const task of snapshot.tasks || []) {
		if (!["PLANNED", "RUNNING"].includes(task.status) || !task.planId) continue;
		const path = remainingPathForTask(task, vehiclesById[task.vehicleId])
			.filter((step) => isInBounds(step, width, height));
		if (path.length >= 2) {
			pathsByVehicle[task.vehicleId] = path;
		}
	}

	return {
		grid,
		rows: height,
		cols: width,
		vehicles,
		frontiers,
		pathsByVehicle,
		tasks: snapshot.tasks || [],
		navigationRequests: snapshot.navigationRequests || [],
		navigationPlans: snapshot.navigationPlans || [],
		heartbeats: snapshot.heartbeats || [],
		events: snapshot.events || [],
		systemStatus: snapshot.systemStatus,
		runtime: snapshot.runtime || {},
		changedCells,
		mapVersion: snapshot.mapDelta ? snapshot.mapDelta.toVersion : map.version,
		mapGeneration: snapshot.mapDelta ? snapshot.mapDelta.generation : map.generation,
		snapshotAt: snapshot.snapshotAt,
	};
}

import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

interface TeamMember {
  id: string;
  name: string;
  role: string;
  avatar?: string;
  status: 'active' | 'busy' | 'offline';
}

interface Team {
  id: string;
  name: string;
  description: string;
  members: TeamMember[];
  createdAt: Date;
  leader: string;
  activeMissions: number;
}

@Component({
  selector: 'app-teams',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './teams.component.html',
  styleUrls: ['./teams.component.scss']
})
export class TeamsComponent implements OnInit {
  teams: Team[] = [];
  selectedTeam: Team | null = null;
  showCreateModal = false;
  showTeamDetailModal = false;

  ngOnInit(): void {
    this.loadTeams();
  }

  loadTeams(): void {
    // Mock data
    this.teams = [
      {
        id: 'TEAM-001',
        name: 'Équipe Alpha',
        description: 'Équipe d\'intervention rapide',
        leader: 'Jean Dupont',
        activeMissions: 3,
        createdAt: new Date('2025-01-15'),
        members: [
          { id: 'M1', name: 'Jean Dupont', role: 'Chef d\'équipe', status: 'active' },
          { id: 'M2', name: 'Marie Martin', role: 'Secouriste', status: 'active' },
          { id: 'M3', name: 'Pierre Dubois', role: 'Logistique', status: 'busy' }
        ]
      },
      {
        id: 'TEAM-002',
        name: 'Équipe Bravo',
        description: 'Support logistique',
        leader: 'Sophie Laurent',
        activeMissions: 1,
        createdAt: new Date('2025-01-20'),
        members: [
          { id: 'M4', name: 'Sophie Laurent', role: 'Chef d\'équipe', status: 'active' },
          { id: 'M5', name: 'Luc Bernard', role: 'Coordinateur', status: 'offline' }
        ]
      }
    ];
  }

  viewTeamDetails(team: Team): void {
    this.selectedTeam = team;
    this.showTeamDetailModal = true;
  }

  openCreateModal(): void {
    this.showCreateModal = true;
  }

  getStatusClass(status: string): string {
    return `status-${status}`;
  }

  getMemberCount(team: Team): number {
    return team.members.length;
  }
}